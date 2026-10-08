import { describe, expect, it } from "vitest";
import { gaugeColor, loadAveragesLabel, loadGaugePercent, otherMountsLabel, smartBadge } from "./gauges";

describe("gaugeColor", () => {
  it("returns success just below warn", () => {
    expect(gaugeColor(79, 80, 90)).toBe("success");
  });

  it("returns warning at the warn threshold", () => {
    expect(gaugeColor(80, 80, 90)).toBe("warning");
  });

  it("returns warning just below crit", () => {
    expect(gaugeColor(89, 80, 90)).toBe("warning");
  });

  it("returns danger at the crit threshold", () => {
    expect(gaugeColor(90, 80, 90)).toBe("danger");
  });

  it("returns success when both thresholds are null, regardless of value", () => {
    expect(gaugeColor(99, null, null)).toBe("success");
  });

  it("returns success for a null value", () => {
    expect(gaugeColor(null, 80, 90)).toBe("success");
  });

  it("returns success for an undefined value", () => {
    expect(gaugeColor(undefined, 80, 90)).toBe("success");
  });
});

describe("smartBadge", () => {
  it("returns null when total is null", () => {
    expect(smartBadge(null, null)).toBeNull();
  });

  it("returns null when total is 0", () => {
    expect(smartBadge(0, 0)).toBeNull();
  });

  it("returns a Pass badge with a count when nothing is failing", () => {
    const badge = smartBadge(2, 0);
    expect(badge?.text).toBe("SMART: Pass (2/2)");
    expect(badge?.color).toBe("success");
  });

  it("returns a Fail badge with a count when something is failing", () => {
    const badge = smartBadge(2, 1);
    expect(badge?.text).toBe("SMART: Fail (1/2)");
    expect(badge?.color).toBe("danger");
  });
});

describe("otherMountsLabel", () => {
  it("returns null for a null percent", () => {
    expect(otherMountsLabel(null)).toBeNull();
  });

  it("returns null for an undefined percent", () => {
    expect(otherMountsLabel(undefined)).toBeNull();
  });

  it("rounds to a whole percent", () => {
    expect(otherMountsLabel(91.4)).toBe("Other mounts: 91% used");
  });
});

describe("loadGaugePercent", () => {
  it("scales load1 against crit and clamps to 0-100", () => {
    expect(loadGaugePercent(2.0, 4.0)).toBe(50);
    expect(loadGaugePercent(5, 4)).toBe(100);
    expect(loadGaugePercent(-1, 4)).toBe(0);
  });

  it("is 0 when crit is unusable and null when there is no reading", () => {
    expect(loadGaugePercent(1, null)).toBe(0);
    expect(loadGaugePercent(1, 0)).toBe(0);
    expect(loadGaugePercent(null, 4)).toBeNull();
    expect(loadGaugePercent(Number.NaN, 4)).toBeNull();
  });
});

describe("loadAveragesLabel", () => {
  it("formats the three averages with two decimals", () => {
    expect(loadAveragesLabel(0.12, 0.3, 0.25)).toBe("1/5/15 min: 0.12 / 0.30 / 0.25");
  });

  it("uses a dash for a missing 5/15 value and is null without load1", () => {
    expect(loadAveragesLabel(1, null, undefined)).toBe("1/5/15 min: 1.00 / - / -");
    expect(loadAveragesLabel(null, 1, 1)).toBeNull();
    expect(loadAveragesLabel(Number.NaN, 1, 1)).toBeNull();
  });
});
