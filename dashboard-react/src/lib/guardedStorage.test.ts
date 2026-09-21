import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readJson, writeJson } from "./guardedStorage";

describe("readJson", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns the parsed stored value", () => {
    localStorage.setItem("k", JSON.stringify({ a: 1 }));
    expect(readJson("k", { a: 0 })).toEqual({ a: 1 });
  });

  it("returns fallback when the key is absent", () => {
    expect(readJson("missing", "default")).toBe("default");
  });

  it("returns fallback without throwing when localStorage.getItem throws", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => readJson("k", "default")).not.toThrow();
    expect(readJson("k", "default")).toBe("default");
    spy.mockRestore();
  });

  it("returns fallback when the stored string is not valid JSON", () => {
    localStorage.setItem("k", "not json{");
    expect(readJson("k", "default")).toBe("default");
  });
});

describe("writeJson", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns true on success", () => {
    expect(writeJson("k", { a: 1 })).toBe(true);
    expect(localStorage.getItem("k")).toBe(JSON.stringify({ a: 1 }));
  });

  it("returns false without throwing when localStorage.setItem throws", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => writeJson("k", { a: 1 })).not.toThrow();
    expect(writeJson("k", { a: 1 })).toBe(false);
    spy.mockRestore();
  });
});
