// The single choke point for the dashboard's MQTT-over-WebSockets lifecycle.
//
// Every listener mqtt.js can emit is attached in this one module and nowhere else --
// components never attach their own listeners to the raw client (useAppStore's
// handleMessage() is the only way a message reaches the rest of the app). This mirrors this
// codebase's existing "one choke point normalizes every failure" shape
// (scripts/mqtt_poller.py::_publish_json()/_livestatus_request()).
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

import mqtt, { type MqttClient } from "mqtt";
import { WS_PORT, WS_USERNAME, WS_PASSWORD } from "../lib/config";
import { useAppStore } from "./useAppStore";

export const BASE_DELAY_MS = 1000;
export const MAX_DELAY_MS = 30000;

export const SUBSCRIBE_TOPICS = [
  "lan/devices/+/status",
  "lan/devices/+/history",
  "lan/devices/+/services",
  "lan/devices/+/service_history",
  "lan/devices/topology",
  "lan/events/recent",
  "lan/poller/status",
  "lan/incidents/+/status", // Phase 14 -- retained delivery on SUBACK gives every open incident
];

export interface ConnectDeps {
  connectFn?: typeof mqtt.connect;
  randomFn?: () => number;
  setTimeoutFn?: typeof globalThis.setTimeout;
}

let client: MqttClient | null = null;
let attempt = 0;
let reconnectTimer: ReturnType<typeof globalThis.setTimeout> | null = null;

let activeRandomFn: () => number = Math.random;
let activeSetTimeoutFn: typeof globalThis.setTimeout = globalThis.setTimeout;

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

  useAppStore.getState().setConnection({ phase: "connecting" });

  // D-02: the broker host is derived at runtime from the page's own origin so the
  // dashboard works unchanged from any LAN device -- nginx and mosquitto are published
  // from the same host.
  const url = `ws://${location.hostname}:${WS_PORT}`;

  client = connectFn(url, {
    username: WS_USERNAME,
    password: WS_PASSWORD,
    reconnectPeriod: 0, // disable mqtt.js's own fixed-interval retry -- see header comment
    clean: true, // default; retained-message delivery on SUBACK is independent of clean-session
  });

  client.on("connect", () => {
    attempt = 0;
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
    }
    // Subscribing is what triggers the broker's retained-message replay on SUBACK -- no
    // cache-warming request of any kind is needed or permitted (11-RESEARCH.md
    // Don't-Hand-Roll table).
    client?.subscribe(SUBSCRIBE_TOPICS);
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
    useAppStore.getState().handleMessage(topic, payload);
  });
}

export function disconnect(): void {
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
}
