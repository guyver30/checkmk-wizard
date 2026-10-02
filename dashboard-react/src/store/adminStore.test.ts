import { beforeEach, describe, expect, it } from "vitest";
import { useAdminStore, __resetAdminStoreForTests } from "./adminStore";

const enc = (v: unknown) => new TextEncoder().encode(JSON.stringify(v));

beforeEach(() => {
  __resetAdminStoreForTests();
});

describe("useAdminStore", () => {
  it("starts empty", () => {
    const s = useAdminStore.getState();
    expect(s.selected.size).toBe(0);
    expect(s.faked).toEqual({});
    expect(s.fakedReceived).toBe(false);
    expect(s.pending).toBeNull();
    expect(s.lastResult).toBeNull();
    expect(s.configError).toBe(false);
  });

  it("toggleSelected adds then removes with a new Set each time", () => {
    const first = useAdminStore.getState().selected;
    useAdminStore.getState().toggleSelected("a");
    const second = useAdminStore.getState().selected;
    expect(second.has("a")).toBe(true);
    expect(second).not.toBe(first);
    useAdminStore.getState().toggleSelected("a");
    expect(useAdminStore.getState().selected.has("a")).toBe(false);
  });

  it("replaceSelection makes the selection exactly the given ids with a new Set", () => {
    useAdminStore.getState().setSelected(["a", "b"], true);
    const before = useAdminStore.getState().selected;
    useAdminStore.getState().replaceSelection(["c", "d"]);
    const after = useAdminStore.getState().selected;
    expect([...after].sort()).toEqual(["c", "d"]);
    expect(after).not.toBe(before);
    expect([...before].sort()).toEqual(["a", "b"]);
    useAdminStore.getState().replaceSelection([]);
    expect(useAdminStore.getState().selected.size).toBe(0);
  });

  it("setSelected and clearSelection", () => {
    useAdminStore.getState().setSelected(["a", "b"], true);
    expect([...useAdminStore.getState().selected].sort()).toEqual(["a", "b"]);
    useAdminStore.getState().setSelected(["a"], false);
    expect([...useAdminStore.getState().selected]).toEqual(["b"]);
    useAdminStore.getState().clearSelection();
    expect(useAdminStore.getState().selected.size).toBe(0);
  });

  it("admin/faked sets the map; malformed keeps it; empty payload clears it", () => {
    useAdminStore.getState().handleAdminMessage("admin/faked", enc({ hosts: { a: "DOWN" } }));
    expect(useAdminStore.getState().faked).toEqual({ a: "DOWN" });
    expect(useAdminStore.getState().fakedReceived).toBe(true);
    useAdminStore.getState().handleAdminMessage("admin/faked", new TextEncoder().encode("{oops"));
    expect(useAdminStore.getState().faked).toEqual({ a: "DOWN" });
    useAdminStore.getState().handleAdminMessage("admin/faked", new Uint8Array(0));
    expect(useAdminStore.getState().faked).toEqual({});
  });

  it("a matching ack clears pending and records the result", () => {
    useAdminStore.getState().setPending({ id: "x", action: "down", hosts: ["a"], sentAtMs: 1 });
    useAdminStore.getState().handleAdminMessage(
      "admin/ack",
      enc({
        id: "x",
        ok: true,
        action: "down",
        detail: "done",
        applied: [{ host: "a", state: "DOWN", cascaded: false }],
        skipped: [],
      }),
    );
    const s = useAdminStore.getState();
    expect(s.pending).toBeNull();
    expect(s.lastResult).toMatchObject({ ok: true, action: "down", count: 1, detail: "done" });
  });

  it("an ack with another id is ignored", () => {
    useAdminStore.getState().setPending({ id: "x", action: "down", hosts: ["a"], sentAtMs: 1 });
    useAdminStore
      .getState()
      .handleAdminMessage(
        "admin/ack",
        enc({ id: "y", ok: true, action: "down", detail: "", applied: [], skipped: [] }),
      );
    expect(useAdminStore.getState().pending?.id).toBe("x");
    expect(useAdminStore.getState().lastResult).toBeNull();
  });

  it("expirePending only acts on the matching id", () => {
    useAdminStore.getState().setPending({ id: "x", action: "up", hosts: ["a"], sentAtMs: 1 });
    useAdminStore.getState().expirePending("other");
    expect(useAdminStore.getState().pending).not.toBeNull();
    useAdminStore.getState().expirePending("x");
    expect(useAdminStore.getState().pending).toBeNull();
    expect(useAdminStore.getState().lastResult).toMatchObject({ ok: false, timedOut: true });
  });

  it("setConfigError toggles the flag", () => {
    useAdminStore.getState().setConfigError(true);
    expect(useAdminStore.getState().configError).toBe(true);
  });
});
