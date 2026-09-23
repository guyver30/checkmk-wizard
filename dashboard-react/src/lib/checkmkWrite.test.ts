import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CheckmkWriteError,
  UNMANAGED_SWITCH_ATTRIBUTES,
  activateChanges,
  countPendingChanges,
  createUnmanagedSwitch,
  isValidHostName,
  setMapPosition,
  updateParents,
} from "./checkmkWrite";
import { TOPOLOGY_EDITOR_SECRET } from "./config";

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
});

describe("request() choke point (exercised via the exported writers)", () => {
  it("throws CheckmkWriteError with method, url, status and parsed body on a non-2xx response", async () => {
    fetchMock.mockResolvedValueOnce(mockResponse(404, { detail: "not found" }));

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
    expect(String(caught)).not.toContain(TOPOLOGY_EDITOR_SECRET);
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
