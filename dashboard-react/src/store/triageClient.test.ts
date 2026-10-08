import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MqttClient } from "mqtt";
import { PUBLISH_TIMEOUT_MS, publishTriage, __resetForTests } from "./triageClient";
import { __setRuntimeConfigForTests } from "../lib/runtimeConfig";
import { buildTriageCommand } from "../lib/triageMode";

function createFakeClient(publishError: Error | null = null) {
  const handlers: Record<string, ((...args: unknown[]) => void)[]> = {};
  const fake = {
    on: vi.fn((event: string, handler: (...args: unknown[]) => void) => {
      (handlers[event] ??= []).push(handler);
      return fake;
    }),
    subscribe: vi.fn(),
    publish: vi.fn(
      (_topic: string, _payload: string, _opts: unknown, cb: (err?: Error | null) => void) => {
        cb(publishError);
      },
    ),
    emit(event: string, ...args: unknown[]) {
      for (const h of handlers[event] ?? []) h(...args);
    },
  };
  return fake;
}

const CONFIG = { wsUsername: "wstriage", wsPassword: "secret" };

beforeEach(() => {
  __setRuntimeConfigForTests({ checkmkSite: "site1" });
  __resetForTests();
});

describe("publishTriage", () => {
  it("connects with the triage login, publishes QoS 1 not retained, never subscribes", async () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);
    const cmd = buildTriageCommand("n1", "downgrade", undefined, undefined, "id1");
    const ok = await publishTriage(cmd, {
      connectFn: connectFn as never,
      loadConfig: async () => CONFIG,
    });
    expect(ok).toBe(true);
    const opts = (connectFn.mock.calls[0] as unknown[])[1];
    expect(opts).toMatchObject({ username: "wstriage", password: "secret", reconnectPeriod: 0 });
    expect(fake.on).toHaveBeenCalledWith("error", expect.any(Function));
    const [topic, payload, pubOpts] = fake.publish.mock.calls[0];
    expect(topic).toBe("sites/site1/needs/triage/cmd");
    expect(JSON.parse(payload)).toEqual({ id: "id1", need_id: "n1", action: "downgrade" });
    expect(pubOpts).toEqual({ qos: 1, retain: false });
    expect(fake.subscribe).not.toHaveBeenCalled();
  });

  it("reuses the connection on later calls", async () => {
    const fake = createFakeClient();
    const connectFn = vi.fn(() => fake as unknown as MqttClient);
    const loadConfig = vi.fn(async () => CONFIG);
    const deps = { connectFn: connectFn as never, loadConfig };
    await publishTriage(buildTriageCommand("n1", "upgrade"), deps);
    await publishTriage(buildTriageCommand("n2", "upgrade"), deps);
    expect(connectFn).toHaveBeenCalledTimes(1);
    expect(loadConfig).toHaveBeenCalledTimes(1);
    expect(fake.publish).toHaveBeenCalledTimes(2);
  });

  it("resolves false when the config is unavailable", async () => {
    const connectFn = vi.fn();
    const ok = await publishTriage(buildTriageCommand("n1", "cancel"), {
      connectFn: connectFn as never,
      loadConfig: async () => null,
    });
    expect(ok).toBe(false);
    expect(connectFn).not.toHaveBeenCalled();
  });

  it("resolves false when the publish errors", async () => {
    const fake = createFakeClient(new Error("nope"));
    const ok = await publishTriage(buildTriageCommand("n1", "cancel"), {
      connectFn: (() => fake) as never,
      loadConfig: async () => CONFIG,
    });
    expect(ok).toBe(false);
  });

  describe("publish timeout", () => {
    afterEach(() => vi.useRealTimers());

    it("resolves false after the timeout when the broker never acks", async () => {
      // IN-02: with reconnectPeriod 0 the publish callback may never fire.
      vi.useFakeTimers();
      const fake = createFakeClient();
      fake.publish.mockImplementation(() => undefined);
      const pending = publishTriage(buildTriageCommand("n1", "cancel"), {
        connectFn: (() => fake) as never,
        loadConfig: async () => CONFIG,
      });
      await vi.advanceTimersByTimeAsync(PUBLISH_TIMEOUT_MS + 1);
      await expect(pending).resolves.toBe(false);
    });

    it("resolves true on a normal ack and clears the timer", async () => {
      // IN-02: the timeout must not outlive a successful publish.
      vi.useFakeTimers();
      const fake = createFakeClient();
      const ok = publishTriage(buildTriageCommand("n1", "cancel"), {
        connectFn: (() => fake) as never,
        loadConfig: async () => CONFIG,
      });
      await vi.advanceTimersByTimeAsync(0);
      await expect(ok).resolves.toBe(true);
      expect(vi.getTimerCount()).toBe(0);
    });
  });
});
