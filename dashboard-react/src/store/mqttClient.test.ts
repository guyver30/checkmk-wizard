import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MqttClient } from "mqtt";
import {
  connect,
  disconnect,
  BASE_DELAY_MS,
  MAX_DELAY_MS,
  SUBSCRIBE_TOPICS,
  __resetForTests,
} from "./mqttClient";
import { useAppStore } from "./useAppStore";

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
  useAppStore.setState(INITIAL_STATE, true);
  __resetForTests();
});

afterEach(() => {
  disconnect();
  __resetForTests();
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

    expect(fake.subscribe).toHaveBeenCalledWith(SUBSCRIBE_TOPICS);
    expect(useAppStore.getState().connection.phase).toBe("connected");
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
    fake.emit("message", "lan/devices/h1/status", payload);

    expect(handleMessageSpy).toHaveBeenCalledWith("lan/devices/h1/status", payload);

    handleMessageSpy.mockRestore();
  });
});
