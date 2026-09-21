import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StateBadge, StateBadgeForState } from "./StateBadge";

const NOW = Date.parse("2026-09-21T12:00:00Z");

describe("StateBadge", () => {
  it("shows STALE instead of the payload's own state when the device is stale", () => {
    render(
      <StateBadge
        device={{ id: "sw-01", state: "OK", staleness: 5, timestamp: "2026-09-21T11:00:00Z" }}
        nowMs={NOW}
      />,
    );
    expect(screen.getByText("STALE")).toBeInTheDocument();
    expect(screen.queryByText("OK")).not.toBeInTheDocument();
  });

  it("reads effectiveState, not the raw state key, so UNREACH renders", () => {
    render(
      <StateBadge
        device={{ id: "sw-01", state: "DOWN", host_state_raw: "UNREACH", timestamp: "2026-09-21T11:59:50Z" }}
        nowMs={NOW}
      />,
    );
    expect(screen.getByText("UNREACH")).toBeInTheDocument();
  });

  it("renders a fresh device's own state", () => {
    render(<StateBadge device={{ id: "sw-01", state: "OK", timestamp: "2026-09-21T11:59:59Z" }} nowMs={NOW} />);
    expect(screen.getByText("OK")).toBeInTheDocument();
  });
});

describe("StateBadgeForState", () => {
  it("renders the given state text directly", () => {
    render(<StateBadgeForState state="DOWN" />);
    expect(screen.getByText("DOWN")).toBeInTheDocument();
  });
});
