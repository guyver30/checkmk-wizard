// In-memory store for every retained MQTT topic the dashboard consumes.
//
// Every topic published by scripts/mqtt_poller.py is already a complete
// snapshot, never a delta: publish_device_status() republishes a device's
// full status dict every cycle, publish_history()/publish_events() are
// handed the already-truncated bounded array in full, publish_topology()
// sends the whole device list, and publish_poller_status() sends the whole
// liveness object. Because the *contract* guarantees a full snapshot on
// every message, this store always REPLACES a slot and never appends to
// one -- appending client-side would double-bound an already-bounded array
// and leak memory on a long-lived kiosk tab. See scripts/mqtt_poller.py for
// the authoritative topic/payload contract; it is not restated here.
//
// This module owns no DOM access and no `mqtt` reference. It receives
// `(topic, payloadBuffer)` from src/store/mqttClient.ts via
// `handleMessage()` and nothing else.
//
// Malformed-payload tolerance mirrors this codebase's own precedent for
// defensively parsing external/restored data
// (scripts/mqtt_poller.py::_normalise_restored_node()'s defensive
// `.get()`/`isinstance` checks) rather than trusting `JSON.parse()`'s
// output shape: a payload that fails to parse, or parses to the wrong
// shape, is dropped and the last-known-good value is kept -- it must never
// throw out of the message handler and blank the page (T-11.1-03).
//
// Every write uses Zustand's DEFAULT merge (`set({...})`) -- passing a truthy second
// "replace" argument to `set` would wipe every other slice and every action function off
// the store (RESEARCH Architecture Pattern 1). The per-device object itself is still
// replaced wholesale, never deep-merged, matching the vanilla store's contract.

import { create } from "zustand";
import type {
  DevicePayload,
  EventEntry,
  HistoryEntry,
  IncidentPayload,
  PollerStatusPayload,
  ServiceEntry,
  ServiceHistoryEntry,
  TopologyPayload,
} from "../lib/types";

export type ConnectionPhase = "connecting" | "connected" | "reconnecting" | "disconnected";

export interface ConnectionState {
  phase: ConnectionPhase;
  delayMs?: number;
}

export interface AppState {
  devices: Record<string, DevicePayload>;
  history: Record<string, HistoryEntry[]>;
  services: Record<string, ServiceEntry[]>;
  serviceHistory: Record<string, ServiceHistoryEntry[]>;
  events: EventEntry[];
  // Phase 14 / D-13: open incidents, keyed by incident id, kept in step with the poller's
  // retained `lan/incidents/{id}/status` topics -- a pure MQTT consumer for this feature.
  incidents: Record<string, IncidentPayload>;
  topology: TopologyPayload | null;
  pollerStatus: PollerStatusPayload | null;
  // Bug fixed 2026-09-16 (ported from state-store.js): the poller's MQTT will
  // (scripts/mqtt_poller.py's `will_set()`) is fixed to `{"status": "offline"}` with no
  // timestamp -- an MQTT will is captured at connect time, so any timestamp baked into it
  // would be the time the poller STARTED, not the time it died, which would look
  // authoritative while being wrong. That means the retained "offline" payload that
  // replaces a dead poller's last heartbeat carries neither `last_poll` nor `since`, so
  // reading only the CURRENT payload discards the last good timestamp the moment the will
  // fires. Remembered here, the same last-known-good posture this store already applies to
  // malformed payloads (see the header comment above).
  lastKnownPollerTimestamp: string | null;
  connection: ConnectionState;
  handleMessage: (topic: string, payload: Uint8Array) => void;
  setConnection: (status: ConnectionState) => void;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

type ParseResult =
  | { ok: true; value: unknown }
  | { ok: false };

// Returns { ok: true, value } on a well-formed, non-empty payload,
// { ok: true, value: null } on MQTT's zero-length tombstone payload, or
// { ok: false } on anything that fails to parse -- the caller keeps
// last-known-good in that case and must not throw.
function parsePayload(payloadBuffer: Uint8Array | null | undefined): ParseResult {
  if (!payloadBuffer || payloadBuffer.length === 0) {
    return { ok: true, value: null };
  }
  try {
    const text = new TextDecoder().decode(payloadBuffer);
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false };
  }
}

export const useAppStore = create<AppState>()((set, get) => ({
  devices: {},
  history: {},
  services: {},
  serviceHistory: {},
  events: [],
  incidents: {},
  topology: null,
  pollerStatus: null,
  lastKnownPollerTimestamp: null,
  connection: { phase: "connecting" },

  setConnection: (status) => {
    set({ connection: status });
  },

  handleMessage: (topic, payload) => {
    // Routes one MQTT message into the store. Parses the topic by splitting on "/" and
    // matching segment positions rather than a single regex over the whole string, because
    // the device id segment (parts[2]) is arbitrary text sourced from Checkmk host names.
    const parts = topic.split("/");

    if (parts[1] === "incidents" && parts[3] === "status") {
      const id = parts[2];
      const parsed = parsePayload(payload);
      if (!parsed.ok) {
        return; // malformed -- ignore, keep last-known-good
      }
      if (parsed.value === null) {
        // Zero-length retained payload is a tombstone -- the incident closed.
        const incidents = { ...get().incidents };
        delete incidents[id];
        set({ incidents });
        return;
      }
      if (!isPlainObject(parsed.value)) {
        return; // wrong shape -- malformed, drop
      }
      set({ incidents: { ...get().incidents, [id]: parsed.value as IncidentPayload } });
      return;
    }

    if (parts[1] === "devices" && parts[3] === "status") {
      const id = parts[2];
      const parsed = parsePayload(payload);
      if (!parsed.ok) {
        return; // malformed -- ignore, keep last-known-good
      }
      if (parsed.value === null) {
        // Zero-length retained payload is MQTT's own tombstone semantic
        // (scripts/mqtt_poller.py::publish_tombstone) -- remove the device and every
        // per-device slice, so a device removed from Checkmk leaves nothing orphaned
        // behind even if its status tombstone arrives before the services/service_history
        // ones.
        const devices = { ...get().devices };
        const history = { ...get().history };
        const services = { ...get().services };
        const serviceHistory = { ...get().serviceHistory };
        delete devices[id];
        delete history[id];
        delete services[id];
        delete serviceHistory[id];
        set({ devices, history, services, serviceHistory });
        return;
      }
      if (!isPlainObject(parsed.value)) {
        return; // wrong shape -- malformed, drop
      }
      set({ devices: { ...get().devices, [id]: parsed.value as DevicePayload } });
      return;
    }

    if (parts[1] === "devices" && parts[3] === "history") {
      const id = parts[2];
      const parsed = parsePayload(payload);
      if (!parsed.ok) {
        return;
      }
      if (parsed.value === null) {
        set({ history: { ...get().history, [id]: [] } });
        return;
      }
      if (!Array.isArray(parsed.value)) {
        return;
      }
      set({ history: { ...get().history, [id]: parsed.value as HistoryEntry[] } });
      return;
    }

    if (parts[1] === "devices" && parts[3] === "services") {
      const id = parts[2];
      const parsed = parsePayload(payload);
      if (!parsed.ok) {
        return;
      }
      if (parsed.value === null) {
        set({ services: { ...get().services, [id]: [] } });
        return;
      }
      if (!Array.isArray(parsed.value)) {
        return;
      }
      set({ services: { ...get().services, [id]: parsed.value as ServiceEntry[] } });
      return;
    }

    if (parts[1] === "devices" && parts[3] === "service_history") {
      const id = parts[2];
      const parsed = parsePayload(payload);
      if (!parsed.ok) {
        return;
      }
      if (parsed.value === null) {
        set({ serviceHistory: { ...get().serviceHistory, [id]: [] } });
        return;
      }
      if (!Array.isArray(parsed.value)) {
        return;
      }
      set({
        serviceHistory: { ...get().serviceHistory, [id]: parsed.value as ServiceHistoryEntry[] },
      });
      return;
    }

    if (topic === "lan/devices/topology") {
      const parsed = parsePayload(payload);
      if (!parsed.ok || parsed.value === null || !isPlainObject(parsed.value)) {
        return;
      }
      set({ topology: parsed.value as TopologyPayload });
      return;
    }

    if (topic === "lan/events/recent") {
      const parsed = parsePayload(payload);
      if (!parsed.ok) {
        return;
      }
      if (parsed.value === null) {
        set({ events: [] });
        return;
      }
      if (!Array.isArray(parsed.value)) {
        return;
      }
      set({ events: parsed.value as EventEntry[] });
      return;
    }

    if (topic === "lan/poller/status") {
      const parsed = parsePayload(payload);
      if (!parsed.ok || parsed.value === null || !isPlainObject(parsed.value)) {
        return;
      }
      const pollerStatus = parsed.value as PollerStatusPayload;
      const raw = pollerStatus.last_poll || pollerStatus.since;
      set({
        pollerStatus,
        lastKnownPollerTimestamp: raw || get().lastKnownPollerTimestamp,
      });
      return;
    }

    // Unknown topic: no-op.
  },
}));
