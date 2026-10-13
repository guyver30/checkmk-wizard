// The single choke point for the dashboard's MQTT-over-WebSockets lifecycle.
//
// Every listener mqtt.js can emit is attached in this one module and nowhere else --
// components never attach their own listeners to the raw client (useAppStore's
// handleMessages() is the only way a message reaches the rest of the app). This mirrors this
// codebase's existing "one choke point normalizes every failure" shape
// (scripts/mqtt_poller.py::_publish_json()/_livestatus_request()).
//
// Incoming messages are coalesced: each one is queued and the queue is applied in one
// useAppStore.handleMessages() call on the next animation frame (50 ms timeout fallback).
// Applying them one at a time used to cause one store set, one React commit and one
// TopologyMap sync pass per message, and a page load replays about one retained topic per
// host back to back (quick 261013-hqy). Arrival order and last-write-wins are unchanged.
//
// This is a module-level singleton, NOT a hook and NOT a component effect body. React 18/19
// StrictMode double-invokes effects in development, which would open two MQTT connections
// if connect() lived inside an effect hook (RESEARCH anti-pattern). `client` is held at
// module scope and connect() returns early when it is already set.
//
// mqtt.js's own `reconnectPeriod` option is a FIXED interval with no growth and no jitter
// (verified against the mqtt.js README, 2026-09-12, per 11-RESEARCH.md Pattern 3/Pitfall 1)
// -- passing a bigger number only changes the fixed interval, it does not satisfy DASH-05's
// "jittered exponential backoff" requirement, and a fixed interval means every open
// dashboard tab would retry in lockstep after a shared broker restart. `reconnectPeriod: 0`
// disables the built-in retry entirely; this module drives every retry itself, from the
// `close` event, with the standard `min(max, base * 2**attempt) * jitter` formula.
//
// Every subscribe/publish topic lives under `sites/<checkmkSite>/` (site id from
// /config.json). The prefix is added and stripped only here (via lib/topics.ts), so the
// stores and components only ever see relative topics.

import mqtt, { type MqttClient } from "mqtt";
import { WS_PORT } from "../lib/config";
import { getRuntimeConfig } from "../lib/runtimeConfig";
import {
  ADMIN_TOPIC_CMD,
  buildAdminCommand,
  isAdminMode,
  newCommandId,
  type AdminAction,
} from "../lib/adminMode";
import { siteTopic, stripSitePrefix, subscribeTopics } from "../lib/topics";
import { useAdminStore } from "./adminStore";
import { useAppStore } from "./useAppStore";

export const BASE_DELAY_MS = 1000;
export const MAX_DELAY_MS = 30000;

export interface ConnectDeps {
  connectFn?: typeof mqtt.connect;
  randomFn?: () => number;
  setTimeoutFn?: typeof globalThis.setTimeout;
  // Schedules the one flush of the message queue. Defaults to requestAnimationFrame (50 ms
  // timeout when rAF is unavailable or the tab is hidden, where rAF never fires).
  scheduleFlushFn?: (cb: () => void) => void;
}

let client: MqttClient | null = null;
let attempt = 0;
let reconnectTimer: ReturnType<typeof globalThis.setTimeout> | null = null;

let activeRandomFn: () => number = Math.random;
let activeSetTimeoutFn: typeof globalThis.setTimeout = globalThis.setTimeout;

const FLUSH_FALLBACK_MS = 50;

function defaultScheduleFlush(cb: () => void): void {
  if (
    typeof requestAnimationFrame === "function" &&
    (typeof document === "undefined" || document.visibilityState !== "hidden")
  ) {
    requestAnimationFrame(() => cb());
    return;
  }
  activeSetTimeoutFn(cb, FLUSH_FALLBACK_MS);
}

let activeScheduleFlushFn: (cb: () => void) => void = defaultScheduleFlush;

// Messages (relative topics) received since the last flush, in arrival order.
let pendingMessages: Array<[string, Uint8Array]> = [];
let flushScheduled = false;
// Bumped by disconnect()/__resetForTests() so a flush scheduled earlier applies nothing.
let flushGeneration = 0;

// Applies every queued message in arrival order. Consecutive app messages go to the app
// store as one batch; an admin message flushes the run before it so the two stores still see
// their messages in the order they arrived.
export function flushPendingMessages(): void {
  flushScheduled = false;
  const batch = pendingMessages;
  pendingMessages = [];
  let run: Array<[string, Uint8Array]> = [];
  for (const message of batch) {
    const [rel, payload] = message;
    if (rel.startsWith("admin/")) {
      if (run.length > 0) {
        useAppStore.getState().handleMessages(run);
        run = [];
      }
      useAdminStore.getState().handleAdminMessage(rel, payload);
    } else {
      run.push(message);
    }
  }
  if (run.length > 0) {
    useAppStore.getState().handleMessages(run);
  }
}

function enqueueMessage(rel: string, payload: Uint8Array): void {
  pendingMessages.push([rel, payload]);
  if (flushScheduled) {
    return;
  }
  flushScheduled = true;
  const generation = flushGeneration;
  activeScheduleFlushFn(() => {
    if (generation === flushGeneration) {
      flushPendingMessages();
    }
  });
}

function scheduleReconnect(): void {
  const growth = BASE_DELAY_MS * 2 ** attempt;
  const capped = Math.min(MAX_DELAY_MS, growth);
  const delay = capped * (0.5 + activeRandomFn() * 0.5);
  attempt += 1;
  useAppStore.getState().setConnection({ phase: "reconnecting", delayMs: delay });
  reconnectTimer = activeSetTimeoutFn(() => {
    client?.reconnect();
  }, delay);
}

export function connect(deps: ConnectDeps = {}): void {
  if (client) {
    return; // StrictMode double-invoke guard -- at most one connection ever exists.
  }

  const connectFn = deps.connectFn ?? mqtt.connect;
  activeRandomFn = deps.randomFn ?? Math.random;
  activeSetTimeoutFn = deps.setTimeoutFn ?? globalThis.setTimeout;
  activeScheduleFlushFn = deps.scheduleFlushFn ?? defaultScheduleFlush;

  useAppStore.getState().setConnection({ phase: "connecting" });

  // D-02: the broker host is derived at runtime from the page's own origin so the
  // dashboard works unchanged from any LAN device -- nginx and mosquitto are published
  // from the same host.
  const url = `ws://${location.hostname}:${WS_PORT}`;
  const { wsUsername, wsPassword, checkmkSite } = getRuntimeConfig();

  client = connectFn(url, {
    username: wsUsername,
    password: wsPassword,
    reconnectPeriod: 0, // disable mqtt.js's own fixed-interval retry -- see header comment
    clean: true, // default; retained-message delivery on SUBACK is independent of clean-session
  });

  client.on("connect", () => {
    attempt = 0;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
    }
    // Messages queued from the previous session land before the reset below, so a stale
    // queued incident cannot be applied after the reset and outlive its closure.
    flushPendingMessages();
    // Subscribing is what triggers the broker's retained-message replay on SUBACK -- no
    // cache-warming request of any kind is needed or permitted (11-RESEARCH.md
    // Don't-Hand-Roll table). Incidents are cleared first so the replay rebuilds them and
    // drops any that closed while disconnected (14-REVIEW CR-02).
    useAppStore.getState().resetIncidents();
    // The retained replay after SUBACK rebuilds needs/forecasts/narrations; a tombstone
    // published while disconnected is never redelivered, so clearing is the only way to
    // drop resolved needs (same CR-02 reasoning as incidents).
    useAppStore.getState().resetAnalytics();
    const withAdmin = isAdminMode() && !useAdminStore.getState().configError;
    client?.subscribe(subscribeTopics(checkmkSite, withAdmin));
    useAppStore.getState().setConnection({ phase: "connected" });
  });

  client.on("close", scheduleReconnect);

  client.on("offline", () => {
    useAppStore.getState().setConnection({ phase: "disconnected" });
  });

  // Always attach an 'error' listener -- an unhandled 'error' event can abort the rest of
  // page initialization and leave a blank page whose only visible symptom is silence
  // (11-RESEARCH.md Pitfall 3). Never rethrow here.
  client.on("error", (err) => {
    console.error("MQTT error", err);
  });

  client.on("message", (topic, payload) => {
    // Drop anything not under this site's prefix (stray legacy or other-site deliveries);
    // defence in depth on top of the broker ACL. Stores only ever see the relative topic.
    const rel = stripSitePrefix(checkmkSite, topic);
    if (rel === null) {
      return;
    }
    enqueueMessage(rel, payload);
  });
}

// Publishes one admin command and records it as pending for ack correlation. Returns the
// command id, or null when not in admin mode / not connected. Never retained: a retained
// command would replay on every poller restart.
export function publishAdminCommand(action: AdminAction, hosts: string[]): string | null {
  if (!isAdminMode() || !client || !client.connected) {
    return null;
  }
  const cmd = buildAdminCommand(action, hosts, newCommandId());
  client.publish(siteTopic(getRuntimeConfig().checkmkSite, ADMIN_TOPIC_CMD), JSON.stringify(cmd), {
    qos: 1,
    retain: false,
  });
  useAdminStore
    .getState()
    .setPending({ id: cmd.id, action, hosts: cmd.hosts, sentAtMs: Date.now() });
  return cmd.id;
}

// Teardown only (no page code calls it): queued messages are dropped rather than applied,
// since any later connect() rebuilds state from the retained replay.
export function disconnect(): void {
  pendingMessages = [];
  flushScheduled = false;
  flushGeneration += 1;
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
  }
  if (client) {
    client.end(true);
  }
}

// Test-only: clears the module-level singleton so each test starts from a clean slate.
// Mirrors state-store.js's reset() posture -- never called by page code.
export function __resetForTests(): void {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
  }
  client = null;
  attempt = 0;
  reconnectTimer = null;
  activeRandomFn = Math.random;
  activeSetTimeoutFn = globalThis.setTimeout;
  activeScheduleFlushFn = defaultScheduleFlush;
  pendingMessages = [];
  flushScheduled = false;
  flushGeneration += 1;
}
