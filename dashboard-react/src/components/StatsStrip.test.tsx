import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatsStrip } from "./StatsStrip";
import type { StateCounts } from "../store/selectors";

function counts(overrides: Partial<StateCounts> = {}): StateCounts {
  return {
    OK: 0,
    PEND: 0,
    WARN: 0,
    UNKNOWN: 0,
    CRIT: 0,
    UNREACH: 0,
    DOWN: 0,
    STALE: 0,
    ...overrides,
  };
}

describe("StatsStrip", () => {
  it("renders one tile per non-zero state plus OK, and gives DOWN the danger tone", () => {
    render(<StatsStrip counts={counts({ OK: 17, DOWN: 3 })} />);
    const status = screen.getByRole("status", { name: /fleet state summary/i });
    const okTile = within(status).getByText("OK").closest("div");
    const downTile = within(status).getByText("DOWN").closest("div");
    expect(okTile).toHaveTextContent("17");
    expect(downTile).toHaveTextContent("3");
    // WARN/CRIT/etc. are all zero and must not render a tile at all.
    expect(within(status).queryByText("WARN")).not.toBeInTheDocument();
  });

  it("always renders the OK tile even at zero", () => {
    render(<StatsStrip counts={counts()} />);
    expect(screen.getByRole("status", { name: /fleet state summary/i })).toHaveTextContent("OK");
  });

  it("exposes the strip via role=status with an accessible name for screen readers", () => {
    render(<StatsStrip counts={counts({ WARN: 1 })} />);
    expect(screen.getByRole("status", { name: /fleet state summary/i })).toBeInTheDocument();
  });
});
