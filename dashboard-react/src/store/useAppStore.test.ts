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

  it("deletes the device on a zero-length payload (tombstone)", () => {
    useAppStore.getState().handleMessage("lan/devices/h1/status", encode({ state: "OK" }));

    useAppStore.getState().handleMessage("lan/devices/h1/status", EMPTY_PAYLOAD);

    expect(useAppStore.getState().devices).not.toHaveProperty("h1");
  });

  it("deletes services too on a zero-length status payload (tombstone)", () => {
    useAppStore.getState().handleMessage("lan/devices/h1/status", encode({ state: "OK" }));
    useAppStore
      .getState()
      .handleMessage(
        "lan/devices/h1/services",
        encode([{ description: "PING", state: "OK", plugin_output: "ok" }]),
      );

    useAppStore.getState().handleMessage("lan/devices/h1/status", EMPTY_PAYLOAD);

    expect(useAppStore.getState().devices).not.toHaveProperty("h1");
    expect(useAppStore.getState().services).not.toHaveProperty("h1");
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

describe("handleMessage - retired history topics", () => {
  it("ignores history and service_history messages without changing state or throwing", () => {
    useAppStore.getState().handleMessage("lan/devices/h1/status", encode({ state: "OK" }));
    const before = useAppStore.getState();

    expect(() => {
      useAppStore.getState().handleMessage("lan/devices/h1/history", encode([{ state: "OK" }]));
      useAppStore
        .getState()
        .handleMessage("lan/devices/h1/service_history", encode([{ description: "PING" }]));
    }).not.toThrow();

    const after = useAppStore.getState();
    expect(after.devices).toEqual(before.devices);
    expect(after.services).toEqual(before.services);
    expect(after).not.toHaveProperty("history");
    expect(after).not.toHaveProperty("serviceHistory");
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

describe("handleMessage - incidents", () => {
  it("puts the parsed object at incidents.incident-a and leaves other slices intact", () => {
    const before = useAppStore.getState();
    useAppStore
      .getState()
      .handleMessage("lan/incidents/incident-a/status", encode({ id: "incident-a", root: "a" }));
    const after = useAppStore.getState();

    expect(after.incidents["incident-a"]).toEqual({ id: "incident-a", root: "a" });
    expect(after.devices).toBe(before.devices);
    expect(after.events).toBe(before.events);
  });

  it("replaces the previous entry wholesale rather than merging", () => {
    useAppStore
      .getState()
      .handleMessage(
        "lan/incidents/incident-a/status",
        encode({ id: "incident-a", root: "a", worst_criticality: "low" }),
      );
    useAppStore
      .getState()
      .handleMessage("lan/incidents/incident-a/status", encode({ id: "incident-a", root: "a" }));

    expect(useAppStore.getState().incidents["incident-a"]).toEqual({ id: "incident-a", root: "a" });
    expect(useAppStore.getState().incidents["incident-a"]).not.toHaveProperty("worst_criticality");
  });

  it("deletes the incident on a zero-length payload (tombstone)", () => {
    useAppStore
      .getState()
      .handleMessage("lan/incidents/incident-a/status", encode({ id: "incident-a", root: "a" }));

    useAppStore.getState().handleMessage("lan/incidents/incident-a/status", EMPTY_PAYLOAD);

    expect(useAppStore.getState().incidents).not.toHaveProperty("incident-a");
  });

  it("keeps the previous value and does not throw on invalid JSON or an array payload", () => {
    useAppStore
      .getState()
      .handleMessage("lan/incidents/incident-a/status", encode({ id: "incident-a", root: "a" }));

    expect(() => {
      useAppStore
        .getState()
        .handleMessage("lan/incidents/incident-a/status", new TextEncoder().encode("{not json"));
    }).not.toThrow();
    expect(useAppStore.getState().incidents["incident-a"]).toEqual({ id: "incident-a", root: "a" });

    expect(() => {
      useAppStore.getState().handleMessage("lan/incidents/incident-a/status", encode(["not", "an", "object"]));
    }).not.toThrow();
    expect(useAppStore.getState().incidents["incident-a"]).toEqual({ id: "incident-a", root: "a" });
  });
});

const NEED = {
  id: "n-abc",
  source: "trend",
  host: "linux1",
  tier: "urgent",
  generated_at: "2026-10-04T11:55:00Z",
};

describe("handleMessage - needs", () => {
  it("stores a valid need keyed by the topic id", () => {
    useAppStore.getState().handleMessage("lan/needs/n-abc/status", encode(NEED));
    expect(useAppStore.getState().needs["n-abc"]?.host).toBe("linux1");
    expect(useAppStore.getState().needs["n-abc"]?.tier).toBe("urgent");
  });

  it("deletes the need on a zero-length payload (tombstone)", () => {
    useAppStore.getState().handleMessage("lan/needs/n-abc/status", encode(NEED));
    useAppStore.getState().handleMessage("lan/needs/n-abc/status", EMPTY_PAYLOAD);
    expect(useAppStore.getState().needs).not.toHaveProperty("n-abc");
  });

  it("keeps the previous value on malformed JSON or an invalid need", () => {
    useAppStore.getState().handleMessage("lan/needs/n-abc/status", encode(NEED));
    useAppStore.getState().handleMessage("lan/needs/n-abc/status", new TextEncoder().encode("{nope"));
    useAppStore.getState().handleMessage("lan/needs/n-abc/status", encode({ id: "n-abc", tier: "bogus" }));
    expect(useAppStore.getState().needs["n-abc"]?.tier).toBe("urgent");
  });
});

describe("handleMessage - forecasts", () => {
  it("stores a forecast by host and deletes it on tombstone", () => {
    useAppStore
      .getState()
      .handleMessage("lan/forecasts/linux1", encode({ host: "linux1", generated_at: "t", fits: [] }));
    expect(useAppStore.getState().forecasts.linux1?.host).toBe("linux1");

    useAppStore.getState().handleMessage("lan/forecasts/linux1", EMPTY_PAYLOAD);
    expect(useAppStore.getState().forecasts).not.toHaveProperty("linux1");
  });

  it("keeps the previous forecast when the payload is malformed", () => {
    useAppStore
      .getState()
      .handleMessage("lan/forecasts/linux1", encode({ host: "linux1", generated_at: "t", fits: [] }));
    useAppStore.getState().handleMessage("lan/forecasts/linux1", encode({ host: "linux1" }));
    expect(useAppStore.getState().forecasts.linux1?.generated_at).toBe("t");
  });
});

describe("handleMessage - narrations", () => {
  const narration = { id: "incident-sw1", headline: "H", sentences: ["a"], tier: null, generated_at: "t" };

  it("stores a narration without creating or altering an incident entry", () => {
    const before = useAppStore.getState().incidents;
    useAppStore.getState().handleMessage("lan/incidents/incident-sw1/narration", encode(narration));
    expect(useAppStore.getState().narrations["incident-sw1"]?.headline).toBe("H");
    expect(useAppStore.getState().incidents).toBe(before);
    expect(useAppStore.getState().incidents).not.toHaveProperty("incident-sw1");
  });

  it("deletes the narration on tombstone", () => {
    useAppStore.getState().handleMessage("lan/incidents/incident-sw1/narration", encode(narration));
    useAppStore.getState().handleMessage("lan/incidents/incident-sw1/narration", EMPTY_PAYLOAD);
    expect(useAppStore.getState().narrations).not.toHaveProperty("incident-sw1");
  });
});

describe("resetAnalytics", () => {
  it("empties needs, forecasts and narrations but leaves incidents", () => {
    const s = useAppStore.getState();
    s.handleMessage("lan/needs/n-abc/status", encode(NEED));
    s.handleMessage("lan/forecasts/linux1", encode({ host: "linux1", generated_at: "t", fits: [] }));
    s.handleMessage("lan/incidents/incident-a/status", encode({ id: "incident-a", root: "a" }));
    s.resetAnalytics();
    const after = useAppStore.getState();
    expect(after.needs).toEqual({});
    expect(after.forecasts).toEqual({});
    expect(after.narrations).toEqual({});
    expect(Object.keys(after.incidents)).toEqual(["incident-a"]);
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
