import { describe, expect, it, vi } from "vitest";
import { HISTORY_SQL, fetchHourlyHistory } from "./historyClient";

function okFetch(body: unknown): typeof fetch {
  return vi.fn(async () => new Response(JSON.stringify(body), { status: 200 })) as unknown as typeof fetch;
}

describe("fetchHourlyHistory", () => {
  it("sends the constant SQL with typed param_* values and no credentials", async () => {
    const fn = okFetch({ data: [] });
    await fetchHourlyHistory("host'; DROP", "Filesystem /", "fs_used_percent", 30, fn);
    const mock = fn as unknown as ReturnType<typeof vi.fn>;
    const [url, init] = mock.mock.calls[0] as [string, RequestInit];
    expect(url.startsWith("/ch-api/?")).toBe(true);
    const q = new URL(url, "http://x").searchParams;
    expect(q.get("query")).toBe(HISTORY_SQL);
    expect(q.get("param_h")).toBe("host'; DROP");
    expect(q.get("param_s")).toBe("Filesystem /");
    expect(q.get("param_m")).toBe("fs_used_percent");
    expect(q.get("param_d")).toBe("30");
    expect(q.has("user")).toBe(false);
    expect(q.has("password")).toBe(false);
    expect(init.cache).toBe("no-store");
    expect(init.signal).toBeDefined();
  });

  it("parses rows, converts string timestamps and drops non-finite values", async () => {
    const fn = okFetch({
      data: [
        { t: 1700000000, v: 42.5 },
        { t: "1700003600", v: 43 },
        { t: 1700007200, v: null },
        { t: 1700010800, v: "nan" },
      ],
    });
    const result = await fetchHourlyHistory("h", "s", "m", 14, fn);
    expect(result).toEqual({
      ok: true,
      points: [
        { t: 1700000000, v: 42.5 },
        { t: 1700003600, v: 43 },
      ],
    });
  });

  it("resolves {ok:false} on a non-2xx response", async () => {
    const fn = vi.fn(async () => new Response("no", { status: 500 })) as unknown as typeof fetch;
    expect(await fetchHourlyHistory("h", "s", "m", 14, fn)).toEqual({ ok: false });
  });

  it("resolves {ok:false} when fetch rejects", async () => {
    const fn = vi.fn(async () => {
      throw new TypeError("network");
    }) as unknown as typeof fetch;
    expect(await fetchHourlyHistory("h", "s", "m", 90, fn)).toEqual({ ok: false });
  });

  it("resolves {ok:false} on a bad JSON body", async () => {
    const fn = vi.fn(async () => new Response("<html>", { status: 200 })) as unknown as typeof fetch;
    expect(await fetchHourlyHistory("h", "s", "m", 14, fn)).toEqual({ ok: false });
  });
});
