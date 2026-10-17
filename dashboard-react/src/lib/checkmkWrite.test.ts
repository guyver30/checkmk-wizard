import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CheckmkWriteError,
  DEPENDS_ON_LABEL,
  SERVICE_CRITICALITY_LABEL,
  UNMANAGED_SWITCH_ATTRIBUTES,
  activateChanges,
  classifyPendingChanges,
  countPendingChanges,
  createUnmanagedSwitch,
  extractCreatedHostName,
  formatDependsOn,
  formatServiceCriticality,
  getHostSummary,
  isHostCreation,
  isValidHostName,
  listPendingChanges,
  parseDependsOnLabel,
  parsePendingChanges,
  parseServiceCriticalityLabel,
  pendingChangeKey,
  probeEditingAvailable,
  setCriticality,
  setDeviceType,
  setMapPosition,
  setServiceCriticality,
  updateDependsOn,
  updateParents,
} from "./checkmkWrite";
import { __setRuntimeConfigForTests } from "./runtimeConfig";

function mockResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name: string) => headers[name] ?? null },
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  // Reset the runtime config so a non-default checkmkSite set by one test can never leak
  // into the next test's "dmc" assertions.
  __setRuntimeConfigForTests();
});

describe("request() choke point (exercised via the exported writers)", () => {
  it("throws CheckmkWriteError with method, url, status and parsed body on a non-2xx response", async () => {
    fetchMock.mockResolvedValue(mockResponse(404, { detail: "not found" }));

    await expect(countPendingChanges()).rejects.toMatchObject({
      method: "GET",
      status: 404,
      body: { detail: "not found" },
    });
    const err = await countPendingChanges().catch((e) => e);
    expect(err.url).toContain("/checkmk-api/dmc/check_mk/api/1.0");
  });

  it("wraps a rejected fetch as CheckmkWriteError with status 0", async () => {
    fetchMock.mockRejectedValueOnce(new Error("network down"));

    await expect(countPendingChanges()).rejects.toMatchObject({ status: 0 });
  });

  it("never includes the Authorization header in a thrown error", async () => {
    fetchMock.mockResolvedValue(mockResponse(500, { detail: "boom" }));

    let caught: CheckmkWriteError | undefined;
    try {
      await countPendingChanges();
    } catch (err) {
      caught = err as CheckmkWriteError;
    }
    expect(caught).toBeInstanceOf(CheckmkWriteError);
    expect(String(caught)).not.toContain("Bearer");
    expect(caught?.message).not.toContain("Bearer");
  });

  // Amended 2026-09-30 (quick 260930-hpy): the browser no longer authenticates itself at all --
  // nginx (or the Vite dev/preview proxy) injects the topology_editor credential server-side.
  it("sends no Authorization header on a GET request", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, { value: [] }, { ETag: "e" }));

    await countPendingChanges();

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
  });

  it("sends no Authorization header on a PUT request", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, { extensions: { attributes: {} } }, { ETag: "e" }),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await updateParents("h1", (parents) => [...parents, "sw"]);

    const [, putInit] = fetchMock.mock.calls[1];
    expect(putInit.headers.Authorization).toBeUndefined();
  });
});

describe("probeEditingAvailable", () => {
  it("resolves true on 200", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, { versions: { checkmk: "2.4.0p35" } }));

    await expect(probeEditingAvailable()).resolves.toBe(true);
    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/version");
  });

  it("resolves false on 401", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(401, { title: "Unauthorized" }));

    await expect(probeEditingAvailable()).resolves.toBe(false);
  });

  it("resolves false on 500", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(500, { title: "boom" }));

    await expect(probeEditingAvailable()).resolves.toBe(false);
  });

  it("resolves false (does not reject) when fetch itself rejects", async () => {
    fetchMock.mockRejectedValueOnce(new Error("network down"));

    await expect(probeEditingAvailable()).resolves.toBe(false);
  });
});

describe("isValidHostName", () => {
  it("accepts letters, digits, underscore, hyphen and dot", () => {
    expect(isValidHostName("sw-1.lan_a")).toBe(true);
  });

  it("rejects a name containing a space or other punctuation", () => {
    expect(isValidHostName("bad name!")).toBe(false);
  });
});

describe("updateParents", () => {
  it("GETs, then PUTs with If-Match, keeping other attributes and dropping meta_data", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(
        200,
        {
          extensions: {
            attributes: {
              ipaddress: "10.0.0.5",
              tag_agent: "cmk-agent",
              labels: { foo: "bar" },
              meta_data: { created_by: "cmkadmin" },
            },
          },
        },
        { ETag: "etag-1" },
      ),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await updateParents("h1", (parents) => [...parents, "sw"]);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [getUrl] = fetchMock.mock.calls[0];
    expect(getUrl).toContain("/objects/host_config/h1");

    const [putUrl, putInit] = fetchMock.mock.calls[1];
    expect(putUrl).toContain("/objects/host_config/h1");
    expect(putInit.headers["If-Match"]).toBe("etag-1");
    const body = JSON.parse(putInit.body);
    expect(body.attributes.meta_data).toBeUndefined();
    expect(body.attributes.ipaddress).toBe("10.0.0.5");
    expect(body.attributes.tag_agent).toBe("cmk-agent");
    expect(body.attributes.labels).toEqual({ foo: "bar" });
    expect(body.attributes.parents).toEqual(["sw"]);
  });

  it("de-duplicates parents", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, { extensions: { attributes: { parents: ["a", "b"] } } }, { ETag: "e" }),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await updateParents("h1", (parents) => [...parents, "b"]);

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.attributes.parents).toEqual(["a", "b"]);
  });

  it("treats a host with no parents attribute as an empty list", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, { extensions: { attributes: {} } }, { ETag: "e" }),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    let seen: string[] | undefined;
    await updateParents("h1", (parents) => {
      seen = parents;
      return parents;
    });

    expect(seen).toEqual([]);
  });

  it("deletes the parents key entirely when the result is empty", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, { extensions: { attributes: { parents: ["a"] } } }, { ETag: "e" }),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await updateParents("h1", () => []);

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(Object.prototype.hasOwnProperty.call(body.attributes, "parents")).toBe(false);
  });

  it("runs two concurrent updateParents calls strictly sequentially", async () => {
    const order: string[] = [];
    let releaseFirstPut: () => void = () => {};
    const firstPutGate = new Promise<void>((resolve) => {
      releaseFirstPut = resolve;
    });

    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "GET" && url.includes("host-a")) {
        order.push("GET host-a");
        return mockResponse(200, { extensions: { attributes: {} } }, { ETag: "etag-a" });
      }
      if (method === "PUT" && url.includes("host-a")) {
        order.push("PUT host-a");
        await firstPutGate;
        return mockResponse(200, {});
      }
      if (method === "GET" && url.includes("host-b")) {
        order.push("GET host-b");
        return mockResponse(200, { extensions: { attributes: {} } }, { ETag: "etag-b" });
      }
      if (method === "PUT" && url.includes("host-b")) {
        order.push("PUT host-b");
        return mockResponse(200, {});
      }
      throw new Error(`unexpected ${method} ${url}`);
    });

    const p1 = updateParents("host-a", (parents) => [...parents, "sw"]);
    const p2 = updateParents("host-b", (parents) => [...parents, "sw"]);

    // Flush every already-queued microtask without letting the gated PUT resolve.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(order).toEqual(["GET host-a", "PUT host-a"]);

    releaseFirstPut();
    await p1;
    await p2;

    expect(order).toEqual(["GET host-a", "PUT host-a", "GET host-b", "PUT host-b"]);
  });
});

describe("setMapPosition", () => {
  it("merges map_position into labels, preserving other labels", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(
        200,
        { extensions: { attributes: { labels: { other: "x" } } } },
        { ETag: "e" },
      ),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await setMapPosition("h1", 119.6, -40.2);

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.attributes.labels).toEqual({ other: "x", map_position: "120,-40" });
  });
});

describe("setCriticality", () => {
  it("PUTs criticality into labels, preserving other labels and non-label attributes", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(
        200,
        {
          extensions: {
            attributes: { ipaddress: "10.0.0.5", labels: { map_position: "1,2" } },
          },
        },
        { ETag: "e" },
      ),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await setCriticality("h1", "high");

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(fetchMock.mock.calls[1][1].headers["If-Match"]).toBe("e");
    expect(body.attributes.ipaddress).toBe("10.0.0.5");
    expect(body.attributes.labels).toEqual({ map_position: "1,2", criticality: "high" });
  });

  it("rejects an invalid tier before any fetch", async () => {
    await expect(setCriticality("h1", "urgent" as never)).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects an invalid host name before any fetch", async () => {
    await expect(setCriticality("bad host", "high")).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("setDeviceType", () => {
  it("PUTs tag_device_type, preserving every other attribute and label", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(
        200,
        {
          extensions: {
            attributes: {
              ipaddress: "10.0.0.5",
              parents: ["sw1"],
              tag_device_type: "other",
              labels: { map_position: "1,2" },
              meta_data: { created_at: "x" },
            },
          },
        },
        { ETag: "e" },
      ),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await setDeviceType("h1", "ACS");

    expect(fetchMock.mock.calls[1][0]).toContain("/objects/host_config/h1");
    expect(fetchMock.mock.calls[1][1].method).toBe("PUT");
    expect(fetchMock.mock.calls[1][1].headers["If-Match"]).toBe("e");
    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.attributes).toEqual({
      ipaddress: "10.0.0.5",
      parents: ["sw1"],
      tag_device_type: "ACS",
      labels: { map_position: "1,2" },
    });
  });

  it("rejects an invalid host name or an empty type before any fetch", async () => {
    await expect(setDeviceType("bad host", "ACS")).rejects.toThrow();
    await expect(setDeviceType("h1", "")).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("surfaces Checkmk's rejection of an unknown tag value", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, { extensions: { attributes: {} } }, { ETag: "e" }));
    fetchMock.mockResolvedValueOnce(mockResponse(400, { title: "Bad Request" }));
    await expect(setDeviceType("h1", "Nope")).rejects.toThrow();
  });
});

describe("setServiceCriticality", () => {
  it("adds a new entry to an existing service_criticality label, entries sorted by name", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(
        200,
        { extensions: { attributes: { labels: { [SERVICE_CRITICALITY_LABEL]: "ModemManager=low" } } } },
        { ETag: "e" },
      ),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await setServiceCriticality("h1", "Systemd Service cron", "critical");

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.attributes.labels[SERVICE_CRITICALITY_LABEL]).toBe(
      "ModemManager=low;Systemd Service cron=critical",
    );
  });

  it("removes an entry when tier is null, deleting the label key entirely when it was the last entry", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(
        200,
        { extensions: { attributes: { labels: { [SERVICE_CRITICALITY_LABEL]: "cron=critical" } } } },
        { ETag: "e" },
      ),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await setServiceCriticality("h1", "cron", null);

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(Object.prototype.hasOwnProperty.call(body.attributes.labels, SERVICE_CRITICALITY_LABEL)).toBe(
      false,
    );
  });

  it("rejects a service name containing ':', ';' or '=' before any fetch", async () => {
    await expect(setServiceCriticality("h1", "bad:name", "low")).rejects.toThrow();
    await expect(setServiceCriticality("h1", "bad;name", "low")).rejects.toThrow();
    await expect(setServiceCriticality("h1", "bad=name", "low")).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("updateDependsOn", () => {
  it("adds a host to an existing depends_on label", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(
        200,
        { extensions: { attributes: { labels: { [DEPENDS_ON_LABEL]: "core" } } } },
        { ETag: "e" },
      ),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await updateDependsOn("screen1", (ids) => [...ids, "media-srv"]);

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.attributes.labels[DEPENDS_ON_LABEL]).toBe("core,media-srv");
  });

  it("drops invalid ids and the host's own id, de-duplicates, and deletes the key when empty", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(
        200,
        { extensions: { attributes: { labels: { [DEPENDS_ON_LABEL]: "core" } } } },
        { ETag: "e" },
      ),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await updateDependsOn("screen1", (ids) => [...ids, "screen1", "bad host!", "core"]);

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.attributes.labels[DEPENDS_ON_LABEL]).toBe("core");
  });

  it("deletes the depends_on key entirely when the result is empty", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(
        200,
        { extensions: { attributes: { labels: { [DEPENDS_ON_LABEL]: "core" } } } },
        { ETag: "e" },
      ),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await updateDependsOn("screen1", () => []);

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(Object.prototype.hasOwnProperty.call(body.attributes.labels, DEPENDS_ON_LABEL)).toBe(false);
  });
});

describe("parseServiceCriticalityLabel / formatServiceCriticality", () => {
  it("parses a valid label value into a name->tier map", () => {
    expect(parseServiceCriticalityLabel("cron=high;sshd=low")).toEqual({
      cron: "high",
      sshd: "low",
    });
  });

  it("drops malformed entries and out-of-vocabulary tiers", () => {
    expect(parseServiceCriticalityLabel("cron=urgent;=low;noeq;sshd=low")).toEqual({
      sshd: "low",
    });
  });

  it("returns an empty map for undefined/non-string input", () => {
    expect(parseServiceCriticalityLabel(undefined)).toEqual({});
    expect(parseServiceCriticalityLabel(42)).toEqual({});
  });

  it("formats a map sorted by name", () => {
    expect(formatServiceCriticality({ sshd: "low", cron: "high" })).toBe("cron=high;sshd=low");
  });
});

describe("parseDependsOnLabel / formatDependsOn", () => {
  it("parses a comma-separated valid host list", () => {
    expect(parseDependsOnLabel("core,media-srv")).toEqual(["core", "media-srv"]);
  });

  it("drops invalid/empty entries", () => {
    expect(parseDependsOnLabel("core,,bad host!,media-srv")).toEqual(["core", "media-srv"]);
  });

  it("returns an empty array for undefined/non-string input", () => {
    expect(parseDependsOnLabel(undefined)).toEqual([]);
  });

  it("formats an id list joined with commas", () => {
    expect(formatDependsOn(["core", "media-srv"])).toBe("core,media-srv");
  });
});

describe("serialize() preserved across the new writers", () => {
  it("runs setCriticality then updateDependsOn strictly sequentially", async () => {
    const order: string[] = [];
    let releaseFirstPut: () => void = () => {};
    const firstPutGate = new Promise<void>((resolve) => {
      releaseFirstPut = resolve;
    });

    fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "GET" && url.includes("host-a")) {
        order.push("GET host-a");
        return mockResponse(200, { extensions: { attributes: {} } }, { ETag: "etag-a" });
      }
      if (method === "PUT" && url.includes("host-a")) {
        order.push("PUT host-a");
        await firstPutGate;
        return mockResponse(200, {});
      }
      if (method === "GET" && url.includes("host-b")) {
        order.push("GET host-b");
        return mockResponse(200, { extensions: { attributes: {} } }, { ETag: "etag-b" });
      }
      if (method === "PUT" && url.includes("host-b")) {
        order.push("PUT host-b");
        return mockResponse(200, {});
      }
      throw new Error(`unexpected ${method} ${url}`);
    });

    const p1 = setCriticality("host-a", "high");
    const p2 = updateDependsOn("host-b", (ids) => [...ids, "sw"]);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(order).toEqual(["GET host-a", "PUT host-a"]);

    releaseFirstPut();
    await p1;
    await p2;

    expect(order).toEqual(["GET host-a", "PUT host-a", "GET host-b", "PUT host-b"]);
  });
});

describe("createUnmanagedSwitch", () => {
  it("POSTs the unmanaged-switch attribute set with bake_agent=false", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));

    await createUnmanagedSwitch("sw-1", { x: 10, y: 20 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/domain-types/host_config/collections/all?bake_agent=false");
    const body = JSON.parse(init.body);
    expect(body).toEqual({
      host_name: "sw-1",
      folder: "/",
      attributes: {
        ...UNMANAGED_SWITCH_ATTRIBUTES,
        labels: { map_position: "10,20", unmanaged_switch: "yes" },
      },
    });
  });

  it("rejects with CheckmkWriteError before any fetch when the name is invalid", async () => {
    await expect(createUnmanagedSwitch("bad name!", { x: 0, y: 0 })).rejects.toBeInstanceOf(
      CheckmkWriteError,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("countPendingChanges", () => {
  it("returns the pending_changes value array length", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, { value: [{ id: "1" }, { id: "2" }] }));

    await expect(countPendingChanges()).resolves.toBe(2);
  });

  it("returns 0 for a missing or non-array value", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, {}));
    await expect(countPendingChanges()).resolves.toBe(0);
  });
});

describe("activateChanges", () => {
  it("resolves without POSTing when there are no pending changes", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, { value: [] }, { ETag: "e" }));

    await activateChanges();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("POSTs activate-changes with force_foreign_changes false and resolves on 204", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, { value: [{ id: "1" }] }, { ETag: "etag-pending" }),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(204, undefined));

    await activateChanges();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, init] = fetchMock.mock.calls[1];
    expect(init.headers["If-Match"]).toBe("etag-pending");
    const body = JSON.parse(init.body);
    expect(body).toEqual({ redirect: false, sites: ["dmc"], force_foreign_changes: false });
  });

  it("polls activation_run by id until is_running is false", async () => {
    vi.useFakeTimers();
    fetchMock
      .mockResolvedValueOnce(mockResponse(200, { value: [{ id: "1" }] }, { ETag: "e" }))
      .mockResolvedValueOnce(mockResponse(200, { id: "act1", extensions: { is_running: true } }))
      .mockResolvedValueOnce(mockResponse(200, { extensions: { is_running: true } }))
      .mockResolvedValueOnce(mockResponse(200, { extensions: { is_running: false } }));

    const promise = activateChanges();
    await vi.advanceTimersByTimeAsync(500);
    await vi.advanceTimersByTimeAsync(500);
    await promise;

    expect(fetchMock).toHaveBeenCalledTimes(4);
    const [pollUrl] = fetchMock.mock.calls[2];
    expect(pollUrl).toContain("/objects/activation_run/act1");
  });

  it("throws CheckmkWriteError after 60 polls when activation never finishes", async () => {
    vi.useFakeTimers();
    let callCount = 0;
    fetchMock.mockImplementation(async () => {
      callCount += 1;
      if (callCount === 1) {
        return mockResponse(200, { value: [{ id: "1" }] }, { ETag: "e" });
      }
      if (callCount === 2) {
        return mockResponse(200, { id: "act1", extensions: { is_running: true } });
      }
      return mockResponse(200, { extensions: { is_running: true } });
    });

    const promise = activateChanges();
    const assertion = expect(promise).rejects.toMatchObject({ body: "activation timed out" });

    for (let i = 0; i < 60; i++) {
      await vi.advanceTimersByTimeAsync(500);
    }

    await assertion;
    expect(callCount).toBe(62);
  });
});

describe("runtime config (quick 260930-ixs)", () => {
  it("builds request URLs from the runtime-configured checkmkSite, not the dmc default", async () => {
    __setRuntimeConfigForTests({ checkmkSite: "mysite" });
    fetchMock.mockResolvedValueOnce(mockResponse(200, { value: [] }, { ETag: "e" }));

    await countPendingChanges();

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("/checkmk-api/mysite/check_mk/api/1.0");
  });

  it("sends the runtime-configured checkmkSite in activateChanges' sites list", async () => {
    __setRuntimeConfigForTests({ checkmkSite: "mysite" });
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, { value: [{ id: "1" }] }, { ETag: "etag-pending" }),
    );
    fetchMock.mockResolvedValueOnce(mockResponse(204, undefined));

    await activateChanges();

    const [, init] = fetchMock.mock.calls[1];
    const body = JSON.parse(init.body);
    expect(body.sites).toEqual(["mysite"]);
  });
});

// quick 261012-fx1: the pending_changes entry shape is NOT live-verified, so these tests pin the
// defensive parser's tolerated phrasings rather than a confirmed wire format.
describe("extractCreatedHostName", () => {
  it.each([
    ["Created new host web01.", "web01"],
    ["Created new host web01", "web01"],
    ["Created host web01.", "web01"],
    ["created new host 'web01'.", "web01"],
    ['Created new host "web01".', "web01"],
    ["Created new host <tt>web01</tt>.", "web01"],
    ["Added host web01", "web01"],
    ["Created new host srv.example.com.", "srv.example.com"],
  ])("extracts the host from %j", (text, expected) => {
    expect(extractCreatedHostName({ text })).toBe(expected);
  });

  it.each([
    ["Modified host web01."],
    ["Created new folder lab."],
    ["Created new host bad name!"],
  ])("returns null for %j", (text) => {
    expect(extractCreatedHostName({ text })).toBeNull();
  });

  it("returns null when text is missing or not a string", () => {
    expect(extractCreatedHostName({})).toBeNull();
    expect(extractCreatedHostName({ text: 5 as unknown as string })).toBeNull();
  });
});

describe("isHostCreation", () => {
  it("is true for a create-host action name in either spelling, any case", () => {
    expect(isHostCreation({ action_name: "create-host" })).toBe(true);
    expect(isHostCreation({ action_name: "CREATE_HOST" })).toBe(true);
  });

  it("is true when a host name can be extracted from the text", () => {
    expect(isHostCreation({ text: "Created new host web01." })).toBe(true);
  });

  it("is false for an unrelated change", () => {
    expect(isHostCreation({ action_name: "edit-host", text: "Modified host web01." })).toBe(false);
  });
});

describe("parsePendingChanges", () => {
  it("returns [] for non-object json or a non-array value", () => {
    expect(parsePendingChanges(null)).toEqual([]);
    expect(parsePendingChanges("x")).toEqual([]);
    expect(parsePendingChanges({})).toEqual([]);
    expect(parsePendingChanges({ value: "nope" })).toEqual([]);
  });

  it("drops non-object entries and tolerates missing fields", () => {
    const result = parsePendingChanges({ value: [null, 3, "s", { id: "a" }] });
    expect(result).toEqual([{ id: "a" }]);
  });

  it("reads fields nested under extensions when absent at the top level", () => {
    const result = parsePendingChanges({
      value: [
        { id: "a", extensions: { user_id: "bob", action_name: "create-host", text: "t", time: 5 } },
      ],
    });
    expect(result).toEqual([
      { id: "a", user_id: "bob", action_name: "create-host", text: "t", time: 5 },
    ]);
  });

  it("accepts numeric or string time and drops other types", () => {
    const result = parsePendingChanges({
      value: [{ time: "2026-10-12" }, { time: 12 }, { time: {} }],
    });
    expect(result).toEqual([{ time: "2026-10-12" }, { time: 12 }, {}]);
  });
});

describe("pendingChangeKey", () => {
  it("uses id when it is a non-empty string", () => {
    expect(pendingChangeKey({ id: "abc", text: "x" })).toBe("abc");
  });

  it("falls back to action_name|text|time", () => {
    expect(pendingChangeKey({ id: "", action_name: "a", text: "t", time: 3 })).toBe("a|t|3");
  });
});

describe("classifyPendingChanges", () => {
  it("buckets foreign host creations, other foreign changes, own changes and unknown shapes", () => {
    const result = classifyPendingChanges([
      { id: "1", user_id: "cmkadmin", text: "Created new host web01." },
      { id: "2", user_id: "cmkadmin", text: "Created new host web01." },
      { id: "3", user_id: "cmkadmin", action_name: "create-host", text: "Odd phrasing" },
      { id: "4", user_id: "bob", text: "Modified folder lab." },
      { id: "5", user_id: "topology_editor", text: "Modified host sw1." },
      { id: "6", user_id: "bob" },
      { id: "7", text: "Created new host web02." },
    ]);
    expect(result.newHosts.map((h) => h.host)).toEqual(["web01", "web02"]);
    expect(result.unnamedHostCreations).toBe(1);
    expect(result.otherForeign).toBe(1);
    expect(result.own).toBe(1);
    expect(result.unknownShape).toBe(1);
    expect(result.allKeys).toHaveLength(7);
  });
});

describe("listPendingChanges / getHostSummary", () => {
  it("listPendingChanges GETs pending_changes and parses the value array", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, { value: [{ id: "1", user_id: "bob", text: "Created new host a." }] }),
    );

    await expect(listPendingChanges()).resolves.toEqual([
      { id: "1", user_id: "bob", text: "Created new host a." },
    ]);
    expect(fetchMock.mock.calls[0][0]).toContain(
      "/domain-types/activation_run/collections/pending_changes",
    );
  });

  it("getHostSummary rejects for an invalid name without fetching", async () => {
    await expect(getHostSummary("bad name!")).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("getHostSummary returns ip and folder", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, {
        extensions: { folder: "/lab", attributes: { ipaddress: "10.0.0.9" } },
      }),
    );

    await expect(getHostSummary("web01")).resolves.toEqual({
      name: "web01",
      ip: "10.0.0.9",
      folder: "/lab",
    });
    expect(fetchMock.mock.calls[0][0]).toContain("/objects/host_config/web01");
  });

  it("getHostSummary returns nulls when ip/folder are not strings", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, { extensions: { attributes: {} } }));

    await expect(getHostSummary("web01")).resolves.toEqual({ name: "web01", ip: null, folder: null });
  });
});

describe("activateChanges foreign-change opt-in (quick 261012-fx1)", () => {
  it("sends force_foreign_changes true when forceForeignChanges is true", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, { value: [{ id: "1" }] }, { ETag: "e" }));
    fetchMock.mockResolvedValueOnce(mockResponse(204, undefined));

    await activateChanges({ forceForeignChanges: true });

    const body = JSON.parse(fetchMock.mock.calls[1][1].body);
    expect(body.force_foreign_changes).toBe(true);
  });

  it("throws 409 without POSTing when a fresh change was not in expectedChangeKeys", async () => {
    fetchMock.mockResolvedValueOnce(
      mockResponse(200, { value: [{ id: "1" }, { id: "new" }] }, { ETag: "e" }),
    );

    await expect(
      activateChanges({ forceForeignChanges: true, expectedChangeKeys: ["1"] }),
    ).rejects.toMatchObject({
      status: 409,
      body: "pending changes changed since confirmation",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("posts normally when every fresh key was expected", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(200, { value: [{ id: "1" }] }, { ETag: "e" }));
    fetchMock.mockResolvedValueOnce(mockResponse(204, undefined));

    await activateChanges({ forceForeignChanges: true, expectedChangeKeys: ["1", "gone"] });

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
