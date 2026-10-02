import { beforeEach, describe, expect, it } from "vitest";
import { __resetMapFocusStoreForTests, useMapFocusStore } from "./mapFocusStore";

describe("mapFocusStore", () => {
  beforeEach(() => __resetMapFocusStoreForTests());

  it("starts with no request", () => {
    expect(useMapFocusStore.getState().request).toBeNull();
  });

  it("increments seq on every request, including a repeat for the same host", () => {
    useMapFocusStore.getState().requestCenter("h1");
    const first = useMapFocusStore.getState().request;
    useMapFocusStore.getState().requestCenter("h1");
    const second = useMapFocusStore.getState().request;
    expect(first).toEqual({ id: "h1", seq: 1 });
    expect(second).toEqual({ id: "h1", seq: 2 });
  });
});
