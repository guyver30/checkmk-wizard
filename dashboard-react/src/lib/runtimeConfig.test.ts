import { beforeEach, describe, expect, it } from "vitest";
import {
  __setRuntimeConfigForTests,
  getRuntimeConfig,
  loadRuntimeConfig,
  parseRuntimeConfig,
} from "./runtimeConfig";

const DEFAULTS = { checkmkSite: "dmc", wsUsername: "wsreader", wsPassword: "wsreader" };

// getRuntimeConfig() is a module-level singleton shared across every test in this file --
// reset it before each test so an earlier loadRuntimeConfig() call can't leak into the next.
beforeEach(() => {
  __setRuntimeConfigForTests();
});

describe("parseRuntimeConfig", () => {
  it("returns exactly the given values when all three fields are valid", () => {
    expect(parseRuntimeConfig({ checkmkSite: "mysite", wsUsername: "u", wsPassword: "p" })).toEqual({
      checkmkSite: "mysite",
      wsUsername: "u",
      wsPassword: "p",
    });
  });

  it.each([{}, null, "string", [1, 2, 3]])("falls back to defaults for %j", (raw) => {
    expect(parseRuntimeConfig(raw)).toEqual(DEFAULTS);
  });

  it("falls back per field: a partial object keeps the valid field and defaults the rest", () => {
    expect(parseRuntimeConfig({ checkmkSite: "mysite" })).toEqual({
      checkmkSite: "mysite",
      wsUsername: "wsreader",
      wsPassword: "wsreader",
    });
  });

  it.each(["", "1abc", "my-site", "a/b", "../x", "a2345678901234567", 42])(
    "falls back checkmkSite to dmc for invalid site id %j",
    (badSite) => {
      expect(parseRuntimeConfig({ checkmkSite: badSite }).checkmkSite).toBe("dmc");
    },
  );

  it("falls back wsUsername/wsPassword to defaults when empty string or non-string", () => {
    expect(parseRuntimeConfig({ wsUsername: "", wsPassword: 42 })).toEqual(DEFAULTS);
  });
});

describe("loadRuntimeConfig", () => {
  function fakeJsonResponse(status: number, body: unknown): Response {
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    } as unknown as Response;
  }

  it("stores and returns the parsed config from a 200 JSON body; getRuntimeConfig then returns it", async () => {
    const fakeFetch = async () =>
      fakeJsonResponse(200, { checkmkSite: "mysite", wsUsername: "u", wsPassword: "p" });

    const result = await loadRuntimeConfig(fakeFetch as unknown as typeof fetch);

    expect(result).toEqual({ checkmkSite: "mysite", wsUsername: "u", wsPassword: "p" });
    expect(getRuntimeConfig()).toEqual({ checkmkSite: "mysite", wsUsername: "u", wsPassword: "p" });
  });

  it("resolves to defaults (never rejects) when fetch rejects", async () => {
    const fakeFetch = async () => {
      throw new Error("network down");
    };

    await expect(loadRuntimeConfig(fakeFetch as unknown as typeof fetch)).resolves.toEqual(DEFAULTS);
  });

  it("resolves to defaults when the response is non-OK (404)", async () => {
    const fakeFetch = async () => fakeJsonResponse(404, {});

    await expect(loadRuntimeConfig(fakeFetch as unknown as typeof fetch)).resolves.toEqual(DEFAULTS);
  });

  it("resolves to defaults when the body is not JSON (vite dev's SPA fallback returns index.html)", async () => {
    const fakeFetch = async () =>
      ({
        ok: true,
        status: 200,
        json: async () => {
          throw new SyntaxError("Unexpected token <");
        },
      }) as unknown as Response;

    await expect(loadRuntimeConfig(fakeFetch as unknown as typeof fetch)).resolves.toEqual(DEFAULTS);
  });

  it("getRuntimeConfig() before any load returns the defaults", () => {
    expect(getRuntimeConfig()).toEqual(DEFAULTS);
  });
});
