import { describe, expect, it } from "vitest";
import { compareServices } from "./serviceSort";
import type { ServiceEntry } from "./types";

describe("compareServices", () => {
  it("sorts a mixed array to CRIT, WARN, UNKNOWN, OK", () => {
    const rows: ServiceEntry[] = [
      { description: "Zpool", state: "OK" },
      { description: "Disk", state: "CRIT" },
      { description: "Update", state: "UNKNOWN" },
      { description: "CPU", state: "WARN" },
    ];

    const sorted = [...rows].sort(compareServices);

    expect(sorted.map((row) => row.state)).toEqual(["CRIT", "WARN", "UNKNOWN", "OK"]);
  });

  it("breaks ties within the same state by description", () => {
    const rows: ServiceEntry[] = [
      { description: "Zpool", state: "CRIT" },
      { description: "Disk", state: "CRIT" },
    ];

    const sorted = [...rows].sort(compareServices);

    expect(sorted.map((row) => row.description)).toEqual(["Disk", "Zpool"]);
  });

  it("puts an entry with a missing state in the UNKNOWN band", () => {
    const rows: ServiceEntry[] = [
      { description: "Missing state" },
      { description: "PING", state: "OK" },
      { description: "Disk", state: "CRIT" },
    ];

    const sorted = [...rows].sort(compareServices);

    expect(sorted.map((row) => row.description)).toEqual(["Disk", "Missing state", "PING"]);
  });
});
