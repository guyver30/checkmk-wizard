import { describe, expect, it } from "vitest";
import { badgeForState } from "./stateMapping";

describe("badgeForState", () => {
  it("maps OK to a soft success badge", () => {
    expect(badgeForState("OK")).toEqual({ color: "success", variant: "soft", iconName: null, label: "OK" });
  });

  it("maps WARN to a soft warning badge", () => {
    expect(badgeForState("WARN")).toEqual({ color: "warning", variant: "soft", iconName: null, label: "WARN" });
  });

  it("maps DOWN to a solid danger badge", () => {
    expect(badgeForState("DOWN")).toEqual({ color: "danger", variant: "solid", iconName: null, label: "DOWN" });
  });

  it("maps CRIT to a danger badge distinguishable from DOWN by variant, not identical to it", () => {
    const crit = badgeForState("CRIT");
    const down = badgeForState("DOWN");
    expect(crit.color).toBe("danger");
    expect(crit.variant).not.toBe(down.variant);
    expect(crit).not.toEqual(down);
  });

  it("maps UNREACH to a mapping distinct from DOWN's", () => {
    const unreach = badgeForState("UNREACH");
    const down = badgeForState("DOWN");
    expect(unreach).not.toEqual(down);
  });

  it("maps STALE to a neutral badge with a non-null icon", () => {
    const stale = badgeForState("STALE");
    expect(stale.color).toBe("neutral");
    expect(stale.iconName).not.toBeNull();
  });

  it("maps UNKNOWN to a black badge with a non-null icon different from STALE's", () => {
    const unknown = badgeForState("UNKNOWN");
    const stale = badgeForState("STALE");
    expect(unknown.color).toBe("black");
    expect(unknown.iconName).not.toBeNull();
    expect(unknown.iconName).not.toBe(stale.iconName);
  });

  it("maps PEND to a neutral mapping and does not throw", () => {
    expect(() => badgeForState("PEND")).not.toThrow();
    expect(badgeForState("PEND").color).toBe("neutral");
  });

  it("falls back to the UNKNOWN mapping for an unrecognised state", () => {
    expect(badgeForState("TOTALLY_BOGUS")).toEqual(badgeForState("UNKNOWN"));
  });

  it("gives all eight states a visually distinct color/variant pair", () => {
    const states = ["OK", "PEND", "WARN", "UNKNOWN", "CRIT", "UNREACH", "DOWN", "STALE"];
    const pairs = new Set(states.map((state) => `${badgeForState(state).color}/${badgeForState(state).variant}`));
    expect(pairs.size).toBe(8);
  });

  it("keeps STALE and UNKNOWN distinguishable by more than color alone", () => {
    const stale = badgeForState("STALE");
    const unknown = badgeForState("UNKNOWN");
    expect(stale.color).not.toBe(unknown.color);
    expect(stale.iconName).not.toBe(unknown.iconName);
  });
});
