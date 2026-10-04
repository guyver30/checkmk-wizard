import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IClientOptions, MqttClient } from "mqtt";
import {
  connect,
  disconnect,
  BASE_DELAY_MS,
  MAX_DELAY_MS,
  publishAdminCommand,
  __resetForTests,
} from "./mqttClient";
import { useAdminStore, __resetAdminStoreForTests } from "./adminStore";
import { __setAdminModeForTests } from "../lib/adminMode";
import { useAppStore } from "./useAppStore";
import { __setRuntimeConfigForTests } from "../lib/runtimeConfig";
import { RELATIVE_SUBSCRIBE_TOPICS, subscribeTopics } from "../lib/topics";

// A hand-written fake mqtt.js client: an on(event, handler) recorder plus subscribe/
// reconnect/end spies, matching the minimum surface mqttClient.ts touches.
function createFakeClient() {
  const handlers: Record<string, ((...args: unknown[]) => void)[]> = {};
  const fake = {
    on: vi.fn((event: string, handler: (...args: unknown[]) => void) => {
      (handlers[event] ??= []).push(handler);
      return fake;
    }),
    subscribe: vi.fn(),
    publish: vi.fn(),
    connected: true,
    reconnect: vi.fn(),
    end: vi.fn(),
    emit(event: string, ...args: unknown[]) {
      for (const handler of handlers[event] ?? []) {
        handler(...args);
      }
    },
  };
  return fake;
}

// A minimal setTimeout fake that captures the delay instead of scheduling anything, cast to
// the real setTimeout type since mqttClient.ts only ever calls it with (cb, delay).
function createFakeSetTimeout(capturedDelays: number[]): typeof globalThis.setTimeout {
  return vi.fn((_cb: () => void, delay: number) => {
    capturedDelays.push(delay);
    return 0;
  }) as unknown as typeof globalThis.setTimeout;
}

const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  __setRuntimeConfigForTests({ checkmkSite: "site1" });
  useAppStore.setState(INITIAL_STATE, true);
  __resetForTests();
  __resetAdminStoreForTests();
});

afterEach(() => {
  __setAdminModeForTests(false);
  disconnect();
  __resetForTests();
  // Reset the runtime config so a non-default wsUsername/wsPassword set by one test can
  // never leak into another test's connect() call.
  __setRuntimeConfigForTests();
});

describe("RELATIVE_SUBSCRIBE_TOPICS", () => {
  it("includes the services wildcard topic but not the retired history topics", () => {
    expect(RELATIVE_SUBSCRIBE_TOPICS).toContain("lan/devices/+/services");
    expect(RELATIVE_SUBSCRIBE_TOPICS).not.toContain("lan/devices/+/history");
    expect(RELATIVE_SUBSCRIBE_TOPICS).not.toContain("lan/devices/+/service_history");
  });

  it("includes the Phase 14 incident wildcard topic", () => {
    expect(RELATIVE_SUBSCRIBE_TOPICS).toContain("lan/incidents/+/status");
  });
});

describe("connect", () => {
  it("creates exactly one underlying client even when called twice (StrictMode guard)", () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);

    connect({ connectFn });
    connect({ connectFn });

    expect(connectFn).toHaveBeenCalledTimes(1);
  });

  it("subscribes to all five topics and sets phase to connected on connect, resetting attempt", () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);

    connect({ connectFn });
    fake.emit("connect");

    expect(fake.subscribe).toHaveBeenCalledWith(subscribeTopics("site1", false));
    expect(useAppStore.getState().connection.phase).toBe("connected");
  });

  it("passes the runtime-configured wsUsername/wsPassword to connectFn (quick 260930-ixs)", () => {
    __setRuntimeConfigForTests({ wsUsername: "u2", wsPassword: "p2" });
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);

    connect({ connectFn });

    const [, options] = connectFn.mock.calls[0] as unknown as [string, IClientOptions];
    expect(options).toMatchObject({ username: "u2", password: "p2" });
  });

  it("drops incidents on reconnect so ones closed while disconnected don't linger", () => {
    // Regression for 14-REVIEW CR-02: a tombstone published while the tab was offline is
    // never delivered, and a cleared retained topic replays nothing.
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);
    connect({ connectFn });
    fake.emit("connect");
    useAppStore.getState().handleMessage("lan/incidents/incident-a/status", new TextEncoder().encode('{"id":"incident-a","root":"a"}'));
    expect(Object.keys(useAppStore.getState().incidents)).toEqual(["incident-a"]);

    fake.emit("connect"); // reconnect; the broker replays nothing for the closed incident

    expect(useAppStore.getState().incidents).toEqual({});
  });

  it("drops needs, forecasts and narrations on every connect before the retained replay", () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);
    connect({ connectFn });
    fake.emit("connect");
    const enc = (v: unknown) => new TextEncoder().encode(JSON.stringify(v));
    const state = useAppStore.getState();
    state.handleMessage(
      "lan/needs/n1/status",
      enc({ id: "n1", source: "trend", host: "h", tier: "urgent" }),
    );
    state.handleMessage("lan/forecasts/h", enc({ host: "h", generated_at: "t", fits: [] }));
    state.handleMessage(
      "lan/incidents/incident-h/narration",
      enc({ headline: "H", sentences: [] }),
    );
    expect(Object.keys(useAppStore.getState().needs)).toEqual(["n1"]);

    fake.emit("connect");

    expect(useAppStore.getState().needs).toEqual({});
    expect(useAppStore.getState().forecasts).toEqual({});
    expect(useAppStore.getState().narrations).toEqual({});
  });

  it("schedules a reconnect with jittered exponential backoff on close", () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);
    const randomFn = () => 0.5; // jitter multiplier = 0.5 + 0.5*0.5 = 0.75
    const capturedDelays: number[] = [];
    const setTimeoutFn = createFakeSetTimeout(capturedDelays);

    connect({ connectFn, randomFn, setTimeoutFn });
    fake.emit("close");

    expect(capturedDelays[0]).toBe(BASE_DELAY_MS * 0.75);
    expect(useAppStore.getState().connection.phase).toBe("reconnecting");
    expect(useAppStore.getState().connection.delayMs).toBe(BASE_DELAY_MS * 0.75);
  });

  it("produces strictly growing base delays for successive close events, capped at MAX_DELAY_MS", () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);
    const randomFn = () => 0; // jitter multiplier = 0.5, isolates the base-delay sequence
    const capturedDelays: number[] = [];
    const setTimeoutFn = createFakeSetTimeout(capturedDelays);

    connect({ connectFn, randomFn, setTimeoutFn });
    fake.emit("close"); // attempt 0 -> base 1000
    fake.emit("close"); // attempt 1 -> base 2000
    fake.emit("close"); // attempt 2 -> base 4000
    fake.emit("close"); // attempt 3 -> base 8000

    const bases = capturedDelays.map((d) => d / 0.5);
    expect(bases).toEqual([1000, 2000, 4000, 8000]);

    // Advance far enough that 1000 * 2**attempt would exceed MAX_DELAY_MS.
    for (let i = 0; i < 10; i += 1) {
      fake.emit("close");
    }
    const lastBase = capturedDelays[capturedDelays.length - 1] / 0.5;
    expect(lastBase).toBe(MAX_DELAY_MS);
  });

  it("applies the jitter multiplier: randomFn returning 0 halves the capped base", () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);
    const randomFn = () => 0;
    const capturedDelays: number[] = [];
    const setTimeoutFn = createFakeSetTimeout(capturedDelays);

    connect({ connectFn, randomFn, setTimeoutFn });
    fake.emit("close");

    expect(capturedDelays[0]).toBe(BASE_DELAY_MS * 0.5);
  });

  it("sets phase to disconnected on offline", () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);

    connect({ connectFn });
    fake.emit("offline");

    expect(useAppStore.getState().connection.phase).toBe("disconnected");
  });

  it("logs an error event and does not rethrow", () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    connect({ connectFn });
    expect(() => fake.emit("error", new Error("boom"))).not.toThrow();
    expect(errorSpy).toHaveBeenCalled();

    errorSpy.mockRestore();
  });

  it("routes each message event to useAppStore.getState().handleMessage", () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);
    const handleMessageSpy = vi.spyOn(useAppStore.getState(), "handleMessage");

    connect({ connectFn });
    const payload = new TextEncoder().encode(JSON.stringify({ state: "OK" }));
    fake.emit("message", "sites/site1/lan/devices/h1/status", payload);

    expect(handleMessageSpy).toHaveBeenCalledWith("lan/devices/h1/status", payload);

    handleMessageSpy.mockRestore();
  });
});

describe("site namespace", () => {
  it("drops legacy-namespace and other-site messages before any store", () => {
    __setAdminModeForTests(true);
    const fake = createFakeClient();
    connect({ connectFn: vi.fn(() => fake as unknown as MqttClient) });
    const appSpy = vi.spyOn(useAppStore.getState(), "handleMessage");
    const adminSpy = vi.spyOn(useAdminStore.getState(), "handleAdminMessage");
    const body = new TextEncoder().encode("{}");
    fake.emit("message", "lan/devices/h1/status", body);
    fake.emit("message", "admin/faked", body);
    fake.emit("message", "sites/other/lan/devices/h1/status", body);
    expect(appSpy).not.toHaveBeenCalled();
    expect(adminSpy).not.toHaveBeenCalled();
    appSpy.mockRestore();
    adminSpy.mockRestore();
  });
});

describe("admin mode", () => {
  it("subscribes only the normal topics outside admin mode", () => {
    const fake = createFakeClient();
    connect({ connectFn: vi.fn(() => fake as unknown as MqttClient) });
    fake.emit("connect");
    expect(fake.subscribe).toHaveBeenCalledWith(subscribeTopics("site1", false));
  });

  it("adds admin topics in admin mode", () => {
    __setAdminModeForTests(true);
    const fake = createFakeClient();
    connect({ connectFn: vi.fn(() => fake as unknown as MqttClient) });
    fake.emit("connect");
    expect(fake.subscribe).toHaveBeenCalledWith(subscribeTopics("site1", true));
  });

  it("skips admin topics when the admin config failed to load", () => {
    __setAdminModeForTests(true);
    useAdminStore.getState().setConfigError(true);
    const fake = createFakeClient();
    connect({ connectFn: vi.fn(() => fake as unknown as MqttClient) });
    fake.emit("connect");
    expect(fake.subscribe).toHaveBeenCalledWith(subscribeTopics("site1", false));
  });

  it("routes admin/ messages to the admin store only", () => {
    __setAdminModeForTests(true);
    const fake = createFakeClient();
    connect({ connectFn: vi.fn(() => fake as unknown as MqttClient) });
    const handleSpy = vi.spyOn(useAppStore.getState(), "handleMessage");
    const body = new TextEncoder().encode(JSON.stringify({ hosts: { a: "DOWN" } }));
    fake.emit("message", "sites/site1/admin/faked", body);
    expect(useAdminStore.getState().faked).toEqual({ a: "DOWN" });
    expect(handleSpy).not.toHaveBeenCalled();
    handleSpy.mockRestore();
  });

  it("still routes lan/ messages to the app store", () => {
    const fake = createFakeClient();
    connect({ connectFn: vi.fn(() => fake as unknown as MqttClient) });
    const handleSpy = vi.spyOn(useAppStore.getState(), "handleMessage");
    const body = new TextEncoder().encode(JSON.stringify({ status: "online" }));
    fake.emit("message", "sites/site1/lan/poller/status", body);
    expect(handleSpy).toHaveBeenCalledWith("lan/poller/status", body);
    handleSpy.mockRestore();
  });

  it("publishAdminCommand publishes QoS 1 non-retained and records pending", () => {
    __setAdminModeForTests(true);
    const fake = createFakeClient();
    connect({ connectFn: vi.fn(() => fake as unknown as MqttClient) });
    const id = publishAdminCommand("down", ["a"]);
    expect(id).not.toBeNull();
    expect(fake.publish).toHaveBeenCalledWith(
      "sites/site1/admin/cmd",
      JSON.stringify({ id, action: "down", hosts: ["a"] }),
      { qos: 1, retain: false },
    );
    expect(useAdminStore.getState().pending?.id).toBe(id);
  });

  it("publishAdminCommand returns null without a connected client or outside admin mode", () => {
    __setAdminModeForTests(true);
    expect(publishAdminCommand("down", ["a"])).toBeNull();
    const fake = createFakeClient();
    fake.connected = false;
    connect({ connectFn: vi.fn(() => fake as unknown as MqttClient) });
    expect(publishAdminCommand("down", ["a"])).toBeNull();
    fake.connected = true;
    __setAdminModeForTests(false);
    expect(publishAdminCommand("down", ["a"])).toBeNull();
    expect(fake.publish).not.toHaveBeenCalled();
  });
});
