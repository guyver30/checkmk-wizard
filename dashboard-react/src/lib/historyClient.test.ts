import { describe, expect, it, vi } from "vitest";
import { HISTORY_SQL, fetchHistorySeries, fetchHourlyHistory } from "./historyClient";

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

describe("fetchHistorySeries", () => {
  const specs = [
    { service: "CPU load", metric: "load1" },
    { service: "CPU load", metric: "load5" },
    { service: "CPU load", metric: "load15" },
  ];

  function byMetricFetch() {
    return vi.fn(async (url: string) => {
      const m = new URL(url, "http://x").searchParams.get("param_m");
      const v = m === "load1" ? 1 : m === "load5" ? 5 : 15;
      return new Response(JSON.stringify({ data: [{ t: 1700000000, v }] }), { status: 200 });
    }) as unknown as typeof fetch;
  }

  it("issues one typed query per series and returns them in input order", async () => {
    const fn = byMetricFetch();
    const result = await fetchHistorySeries("web1", specs, 14, fn);
    const mock = fn as unknown as ReturnType<typeof vi.fn>;
    expect(mock.mock.calls.length).toBe(3);
    for (const [url] of mock.mock.calls as [string][]) {
      expect(url.startsWith("/ch-api/?")).toBe(true);
      const q = new URL(url, "http://x").searchParams;
      expect(q.get("query")).toBe(HISTORY_SQL);
      expect(q.get("param_h")).toBe("web1");
      expect(q.get("param_s")).toBe("CPU load");
      expect(q.get("param_d")).toBe("14");
      expect(q.has("user")).toBe(false);
      expect(q.has("password")).toBe(false);
    }
    expect(result).toEqual({
      ok: true,
      series: [[{ t: 1700000000, v: 1 }], [{ t: 1700000000, v: 5 }], [{ t: 1700000000, v: 15 }]],
    });
  });

  it("fails the whole result when one series fails, without rejecting", async () => {
    let n = 0;
    const fn = vi.fn(async () => {
      n += 1;
      if (n === 2) return new Response("no", { status: 500 });
      return new Response(JSON.stringify({ data: [] }), { status: 200 });
    }) as unknown as typeof fetch;
    expect(await fetchHistorySeries("web1", specs, 14, fn)).toEqual({ ok: false });
    const net = vi.fn(async () => {
      throw new TypeError("network");
    }) as unknown as typeof fetch;
    expect(await fetchHistorySeries("web1", specs, 14, net)).toEqual({ ok: false });
    const html = vi.fn(async () => new Response("<html>", { status: 200 })) as unknown as typeof fetch;
    expect(await fetchHistorySeries("web1", specs, 14, html)).toEqual({ ok: false });
  });

  it("rejects empty, oversized and badly named specs without any request", async () => {
    const fn = byMetricFetch();
    expect(await fetchHistorySeries("web1", [], 14, fn)).toEqual({ ok: false });
    const five = Array.from({ length: 5 }, () => specs[0]);
    expect(await fetchHistorySeries("web1", five, 14, fn)).toEqual({ ok: false });
    expect(await fetchHistorySeries("web1", [{ service: "CPU load", metric: "load1; DROP" }], 14, fn)).toEqual({ ok: false });
    expect(await fetchHistorySeries("web1", [{ service: "", metric: "load1" }], 14, fn)).toEqual({ ok: false });
    expect(await fetchHistorySeries("web1", [{ service: "a\nb", metric: "load1" }], 14, fn)).toEqual({ ok: false });
    expect(await fetchHistorySeries("web1", [{ service: "x".repeat(129), metric: "load1" }], 14, fn)).toEqual({ ok: false });
    expect((fn as unknown as ReturnType<typeof vi.fn>).mock.calls.length).toBe(0);
  });

  it("keeps an empty series as []", async () => {
    const fn = vi.fn(async () => new Response(JSON.stringify({ data: [] }), { status: 200 })) as unknown as typeof fetch;
    expect(await fetchHistorySeries("web1", specs.slice(0, 1), 14, fn)).toEqual({ ok: true, series: [[]] });
  });
});
