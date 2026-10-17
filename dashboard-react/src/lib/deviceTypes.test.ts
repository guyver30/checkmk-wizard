import { describe, expect, it } from "vitest";
import { DEVICE_TYPES, deviceTypeOptions } from "./deviceTypes";

describe("deviceTypes", () => {
  it("lists device_types.json with other first", () => {
    expect(DEVICE_TYPES[0]).toBe("other");
    expect(DEVICE_TYPES).toContain("NetworkDevice");
  });

  it("returns the known types unchanged for a known current type", () => {
    expect(deviceTypeOptions("ACS")).toEqual([...DEVICE_TYPES]);
    expect(deviceTypeOptions(undefined)).toEqual([...DEVICE_TYPES]);
  });

  it("appends an unknown current type so the Select can still show it", () => {
    expect(deviceTypeOptions("unknown")).toEqual([...DEVICE_TYPES, "unknown"]);
  });
});
