// Admin-view state: selection, faked-host map, pending command and last result.
//
// Kept separate from useAppStore so non-admin pages carry no admin state at all (D-12).
// Receives messages only from mqttClient.ts via handleAdminMessage(). Writes use Zustand's
// default merge (`set({...})`), never the replace flag.

import { create } from "zustand";
import {
  ADMIN_TOPIC_ACK,
  ADMIN_TOPIC_FAKED,
  parseAdminAck,
  parseAdminFaked,
  type AdminAckEntry,
  type AdminAction,
  type FakedState,
} from "../lib/adminMode";

export interface AdminPending {
  id: string;
  action: AdminAction;
  hosts: string[];
  sentAtMs: number;
}

export interface AdminResult {
  ok: boolean;
  action: string;
  count: number;
  detail: string;
  atMs: number;
  timedOut?: boolean;
  applied?: AdminAckEntry[];
}

export interface AdminState {
  selected: Set<string>;
  faked: Record<string, FakedState>;
  fakedReceived: boolean;
  pending: AdminPending | null;
  lastResult: AdminResult | null;
  configError: boolean;
  toggleSelected: (id: string) => void;
  setSelected: (ids: string[], on: boolean) => void;
  replaceSelection: (ids: string[]) => void;
  clearSelection: () => void;
  setPending: (p: AdminPending | null) => void;
  expirePending: (id: string) => void;
  setConfigError: (on: boolean) => void;
  handleAdminMessage: (topic: string, payload: Uint8Array) => void;
}

const INITIAL = {
  selected: new Set<string>(),
  faked: {} as Record<string, FakedState>,
  fakedReceived: false,
  pending: null as AdminPending | null,
  lastResult: null as AdminResult | null,
  configError: false,
};

export const useAdminStore = create<AdminState>()((set, get) => ({
  ...INITIAL,

  toggleSelected: (id) => {
    const next = new Set(get().selected);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    set({ selected: next });
  },

  setSelected: (ids, on) => {
    const next = new Set(get().selected);
    for (const id of ids) {
      if (on) {
        next.add(id);
      } else {
        next.delete(id);
      }
    }
    set({ selected: next });
  },

  replaceSelection: (ids) => {
    set({ selected: new Set(ids) });
  },

  clearSelection: () => {
    set({ selected: new Set<string>() });
  },

  setPending: (p) => {
    set({ pending: p });
  },

  expirePending: (id) => {
    const pending = get().pending;
    if (!pending || pending.id !== id) {
      return;
    }
    set({
      pending: null,
      lastResult: {
        ok: false,
        timedOut: true,
        action: pending.action,
        count: 0,
        detail: "No acknowledgement from the poller",
        atMs: Date.now(),
      },
    });
  },

  setConfigError: (on) => {
    set({ configError: on });
  },

  handleAdminMessage: (topic, payload) => {
    let value: unknown = null;
    if (payload && payload.length > 0) {
      try {
        value = JSON.parse(new TextDecoder().decode(payload));
      } catch {
        return; // malformed -- keep last-known-good, never throw
      }
    }
    if (topic === ADMIN_TOPIC_FAKED) {
      set({ faked: parseAdminFaked(value), fakedReceived: true });
      return;
    }
    if (topic === ADMIN_TOPIC_ACK) {
      const ack = parseAdminAck(value);
      const pending = get().pending;
      if (!ack || !pending || pending.id !== ack.id) {
        return;
      }
      set({
        pending: null,
        lastResult: {
          ok: ack.ok,
          action: ack.action,
          count: ack.applied.length,
          detail: ack.detail,
          atMs: Date.now(),
          applied: ack.applied,
        },
      });
    }
  },
}));

// Test-only.
export function __resetAdminStoreForTests(): void {
  useAdminStore.setState({ ...INITIAL, selected: new Set<string>(), faked: {} });
}
