import { describe, expect, it, vi } from "vitest";
import {
  TRIAGE_TOPIC_CMD,
  buildTriageCommand,
  loadTriageConfig,
  parseTriageConfig,
} from "./triageMode";

describe("buildTriageCommand", () => {
  it("builds a command with a fresh id per call", () => {
    const a = buildTriageCommand("n1", "downgrade");
    const b = buildTriageCommand("n1", "downgrade");
    expect(a).toMatchObject({ need_id: "n1", action: "downgrade" });
    expect(a.id).not.toBe(b.id);
  });

  it("omits empty optional fields", () => {
    const cmd = buildTriageCommand("n1", "cancel", "   ", "");
    expect(cmd).not.toHaveProperty("note");
    expect(cmd).not.toHaveProperty("by");
  });

  it("trims and caps note at 200 and by at 64", () => {
    const cmd = buildTriageCommand("n1", "cancel", ` ${"x".repeat(300)} `, "y".repeat(100), "fixed");
    expect(cmd.note).toHaveLength(200);
    expect(cmd.by).toHaveLength(64);
    expect(cmd.id).toBe("fixed");
  });

  it("uses the relative command topic", () => {
    expect(TRIAGE_TOPIC_CMD).toBe("needs/triage/cmd");
  });
});

describe("parseTriageConfig", () => {
  it("accepts non-empty string credentials", () => {
    expect(parseTriageConfig({ wsUsername: "u", wsPassword: "p" })).toEqual({
      wsUsername: "u",
      wsPassword: "p",
    });
  });

  it.each([null, [], "x", {}, { wsUsername: "", wsPassword: "p" }, { wsUsername: "u", wsPassword: 1 }])(
    "rejects %j",
    (raw) => {
      expect(parseTriageConfig(raw)).toBeNull();
    },
  );
});

describe("loadTriageConfig", () => {
  it("resolves the parsed config", async () => {
    const fetchFn = vi.fn(async (..._args: unknown[]) => new Response(JSON.stringify({ wsUsername: "u", wsPassword: "p" })));
    expect(await loadTriageConfig(fetchFn as unknown as typeof fetch)).toEqual({
      wsUsername: "u",
      wsPassword: "p",
    });
    expect(fetchFn.mock.calls[0][0]).toBe("/triage-config.json");
  });

  it("resolves null on 404, network error and bad JSON", async () => {
    expect(await loadTriageConfig((async () => new Response("", { status: 404 })) as typeof fetch)).toBeNull();
    expect(
      await loadTriageConfig((async () => {
        throw new Error("down");
      }) as typeof fetch),
    ).toBeNull();
    expect(await loadTriageConfig((async () => new Response("<html>")) as typeof fetch)).toBeNull();
  });
});
