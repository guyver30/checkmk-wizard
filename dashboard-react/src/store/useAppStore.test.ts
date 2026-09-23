import { beforeEach, describe, expect, it } from "vitest";
import { useAppStore } from "./useAppStore";

// Reset choice: useAppStore.setState(initialState, true) in beforeEach, using a snapshot of
// the store's state captured once before any test mutates it. The `true` replace argument is
// fine here -- it's the TEST harness resetting the whole store between cases, not production
// code merging a message (which must never use it; see useAppStore.ts's header comment).
const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
});

function encode(value: unknown): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(value));
}

const EMPTY_PAYLOAD = new Uint8Array(0);

describe("handleMessage - device status", () => {
  it("puts the parsed object at devices.h1 and leaves other slices/actions intact", () => {
    const before = useAppStore.getState();
    useAppStore.getState().handleMessage("lan/devices/h1/status", encode({ state: "OK" }));
    const after = useAppStore.getState();

    expect(after.devices.h1).toEqual({ state: "OK" });
    expect(after.events).toBe(before.events);
    expect(after.topology).toBe(before.topology);
    expect(after.pollerStatus).toBe(before.pollerStatus);
    expect(after.handleMessage).toBe(before.handleMessage);
  });

  it("replaces the previous object wholesale rather than merging", () => {
    useAppStore.getState().handleMessage(
      "lan/devices/h1/status",
      encode({ state: "OK", alias: "Tower B" }),
    );
    useAppStore.getState().handleMessage("lan/devices/h1/status", encode({ state: "CRIT" }));

    expect(useAppStore.getState().devices.h1).toEqual({ state: "CRIT" });
    expect(useAppStore.getState().devices.h1).not.toHaveProperty("alias");
  });

  it("deletes the device and its history on a zero-length payload (tombstone)", () => {
    useAppStore.getState().handleMessage("lan/devices/h1/status", encode({ state: "OK" }));
    useAppStore.getState().handleMessage("lan/devices/h1/history", encode([{ state: "OK" }]));

    useAppStore.getState().handleMessage("lan/devices/h1/status", EMPTY_PAYLOAD);

    expect(useAppStore.getState().devices).not.toHaveProperty("h1");
    expect(useAppStore.getState().history).not.toHaveProperty("h1");
  });

  it("deletes services and serviceHistory too on a zero-length status payload (tombstone)", () => {
    useAppStore.getState().handleMessage("lan/devices/h1/status", encode({ state: "OK" }));
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/services",
        encode([{ description: "PING", state: "OK", plugin_output: "ok" }]),
      );
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/service_history",
        encode([{ timestamp: "2026-09-21T10:00:00Z", description: "PING", from: "OK", to: "CRIT" }]),
      );

    useAppStore.getState().handleMessage("lan/devices/h1/status", EMPTY_PAYLOAD);

    expect(useAppStore.getState().devices).not.toHaveProperty("h1");
    expect(useAppStore.getState().history).not.toHaveProperty("h1");
    expect(useAppStore.getState().services).not.toHaveProperty("h1");
    expect(useAppStore.getState().serviceHistory).not.toHaveProperty("h1");
  });

  it("keeps the previous value and does not throw on invalid JSON", () => {
    useAppStore.getState().handleMessage("lan/devices/h1/status", encode({ state: "OK" }));

    expect(() => {
      useAppStore.getState().handleMessage("lan/devices/h1/status", new TextEncoder().encode("{not json"));
    }).not.toThrow();

    expect(useAppStore.getState().devices.h1).toEqual({ state: "OK" });
  });

  it("drops a wrong-shaped (array) payload, keeping last-known-good", () => {
    useAppStore.getState().handleMessage("lan/devices/h1/status", encode({ state: "OK" }));
    useAppStore.getState().handleMessage("lan/devices/h1/status", encode([1, 2, 3]));

    expect(useAppStore.getState().devices.h1).toEqual({ state: "OK" });
  });
});

describe("handleMessage - services", () => {
  it("puts a well-formed services array at services.h1", () => {
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/services",
        encode([{ description: "PING", state: "OK", plugin_output: "ok" }]),
      );

    expect(useAppStore.getState().services.h1).toEqual([
      { description: "PING", state: "OK", plugin_output: "ok" },
    ]);
  });

  it("keeps the previous value and does not throw on invalid JSON", () => {
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/services",
        encode([{ description: "PING", state: "OK", plugin_output: "ok" }]),
      );

    expect(() => {
      useAppStore
        .getState()
        .handleMessage("lan/devices/h1/services", new TextEncoder().encode("{not json"));
    }).not.toThrow();

    expect(useAppStore.getState().services.h1).toEqual([
      { description: "PING", state: "OK", plugin_output: "ok" },
    ]);
  });

  it("drops a wrong-shaped (object) payload, keeping last-known-good", () => {
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/services",
        encode([{ description: "PING", state: "OK", plugin_output: "ok" }]),
      );
    useAppStore.getState().handleMessage("lan/devices/h1/services", encode({ not: "an array" }));

    expect(useAppStore.getState().services.h1).toEqual([
      { description: "PING", state: "OK", plugin_output: "ok" },
    ]);
  });

  it("sets services.h1 to [] on a zero-length payload", () => {
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/services",
        encode([{ description: "PING", state: "OK", plugin_output: "ok" }]),
      );
    useAppStore.getState().handleMessage("lan/devices/h1/services", EMPTY_PAYLOAD);

    expect(useAppStore.getState().services.h1).toEqual([]);
  });
});

describe("handleMessage - service_history", () => {
  it("puts a well-formed service_history array at serviceHistory.h1", () => {
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/service_history",
        encode([{ timestamp: "2026-09-21T10:00:00Z", description: "PING", from: "OK", to: "CRIT" }]),
      );

    expect(useAppStore.getState().serviceHistory.h1).toEqual([
      { timestamp: "2026-09-21T10:00:00Z", description: "PING", from: "OK", to: "CRIT" },
    ]);
  });

  it("keeps the previous value and does not throw on invalid JSON", () => {
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/service_history",
        encode([{ timestamp: "2026-09-21T10:00:00Z", description: "PING", from: "OK", to: "CRIT" }]),
      );

    expect(() => {
      useAppStore
        .getState()
        .handleMessage("lan/devices/h1/service_history", new TextEncoder().encode("{not json"));
    }).not.toThrow();

    expect(useAppStore.getState().serviceHistory.h1).toEqual([
      { timestamp: "2026-09-21T10:00:00Z", description: "PING", from: "OK", to: "CRIT" },
    ]);
  });

  it("drops a wrong-shaped (object) payload, keeping last-known-good", () => {
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/service_history",
        encode([{ timestamp: "2026-09-21T10:00:00Z", description: "PING", from: "OK", to: "CRIT" }]),
      );
    useAppStore
      .getState()
      .handleMessage("lan/devices/h1/service_history", encode({ not: "an array" }));

    expect(useAppStore.getState().serviceHistory.h1).toEqual([
      { timestamp: "2026-09-21T10:00:00Z", description: "PING", from: "OK", to: "CRIT" },
    ]);
  });

  it("sets serviceHistory.h1 to [] on a zero-length payload", () => {
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/service_history",
        encode([{ timestamp: "2026-09-21T10:00:00Z", description: "PING", from: "OK", to: "CRIT" }]),
      );
    useAppStore.getState().handleMessage("lan/devices/h1/service_history", EMPTY_PAYLOAD);

    expect(useAppStore.getState().serviceHistory.h1).toEqual([]);
  });
});

describe("handleMessage - events", () => {
  it("sets events to [] on a zero-length payload", () => {
    useAppStore.getState().handleMessage("lan/events/recent", encode([{ device_id: "h1" }]));
    useAppStore.getState().handleMessage("lan/events/recent", EMPTY_PAYLOAD);

    expect(useAppStore.getState().events).toEqual([]);
  });

  it("drops a non-array JSON payload", () => {
    useAppStore.getState().handleMessage("lan/events/recent", encode([{ device_id: "h1" }]));
    useAppStore.getState().handleMessage("lan/events/recent", encode({ not: "an array" }));

    expect(useAppStore.getState().events).toEqual([{ device_id: "h1" }]);
  });
});

describe("handleMessage - poller status", () => {
  it("records lastKnownPollerTimestamp and keeps it across a timestamp-less offline", () => {
    useAppStore
      .getState()
      .handleMessage("lan/poller/status", encode({ status: "online", last_poll: "2026-09-21T10:00:00Z" }));
    expect(useAppStore.getState().lastKnownPollerTimestamp).toBe("2026-09-21T10:00:00Z");

    useAppStore.getState().handleMessage("lan/poller/status", encode({ status: "offline" }));
    expect(useAppStore.getState().pollerStatus).toEqual({ status: "offline" });
    expect(useAppStore.getState().lastKnownPollerTimestamp).toBe("2026-09-21T10:00:00Z");
  });
});

describe("handleMessage - unknown topic", () => {
  it("is a no-op and does not throw", () => {
    const before = useAppStore.getState();
    expect(() => {
      useAppStore.getState().handleMessage("lan/some/unknown/topic", encode({ x: 1 }));
    }).not.toThrow();
    expect(useAppStore.getState().devices).toBe(before.devices);
  });
});
