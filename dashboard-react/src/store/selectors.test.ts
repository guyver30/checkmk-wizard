import { describe, expect, it } from "vitest";
import { makeSelectStateCounts, selectConnectionPhase } from "./selectors";
import type { AppState } from "./useAppStore";
import type { DevicePayload } from "../lib/types";

const NOW = Date.parse("2026-09-21T12:00:00Z");

function stateWithDevices(devices: Record<string, DevicePayload>): AppState {
  return {
    devices,
    history: {},
    services: {},
    serviceHistory: {},
    events: [],
    topology: null,
    pollerStatus: null,
    lastKnownPollerTimestamp: null,
    connection: { phase: "connected" },
    handleMessage: () => {},
    setConnection: () => {},
  };
}

function fresh(state: string, extra: Partial<DevicePayload> = {}): DevicePayload {
  return { id: "d", state, timestamp: "2026-09-21T11:59:55Z", ...extra };
}

describe("selectStateCounts", () => {
  it("counts every key, zeros included, over a mixed devices record", () => {
    const devices: Record<string, DevicePayload> = {};
    for (let i = 0; i < 17; i += 1) {
      devices[`ok-${i}`] = fresh("OK");
    }
    for (let i = 0; i < 3; i += 1) {
      devices[`down-${i}`] = fresh("DOWN");
    }
    const selectStateCounts = makeSelectStateCounts(NOW);
    expect(selectStateCounts(stateWithDevices(devices))).toEqual({
      OK: 17,
      DOWN: 3,
      WARN: 0,
      CRIT: 0,
      UNKNOWN: 0,
      UNREACH: 0,
      PEND: 0,
      STALE: 0,
    });
  });

  it("counts a stale device under STALE and not under its reported state", () => {
    const selectStateCounts = makeSelectStateCounts(NOW);
    const counts = selectStateCounts(
      stateWithDevices({
        host1: { id: "host1", state: "OK", staleness: 5, timestamp: "2026-09-21T10:00:00Z" },
      }),
    );
    expect(counts.STALE).toBe(1);
    expect(counts.OK).toBe(0);
  });

  it("counts a device whose host_state_raw is UNREACH under UNREACH, not DOWN", () => {
    const selectStateCounts = makeSelectStateCounts(NOW);
    const counts = selectStateCounts(
      stateWithDevices({
        host1: fresh("DOWN", { host_state_raw: "UNREACH" }),
      }),
    );
    expect(counts.UNREACH).toBe(1);
    expect(counts.DOWN).toBe(0);
  });

  it("returns all zeros for an empty devices record and does not throw", () => {
    const selectStateCounts = makeSelectStateCounts(NOW);
    expect(() => selectStateCounts(stateWithDevices({}))).not.toThrow();
    expect(selectStateCounts(stateWithDevices({}))).toEqual({
      OK: 0,
      PEND: 0,
      WARN: 0,
      UNKNOWN: 0,
      CRIT: 0,
      UNREACH: 0,
      DOWN: 0,
      STALE: 0,
    });
  });
});

describe("selectConnectionPhase", () => {
  it("returns the store's current connection phase", () => {
    const state = stateWithDevices({});
    state.connection = { phase: "reconnecting", delayMs: 2000 };
    expect(selectConnectionPhase(state)).toBe("reconnecting");
  });
});
