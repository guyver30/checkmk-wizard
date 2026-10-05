import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TierMarker } from "./TierMarker";

describe("TierMarker", () => {
  // 2026-10-05: standard used to render nothing and urgent was a ring; every tier is now a filled
  // dot whose colour differs (red / orange / yellow) and whose aria-label names the tier.
  it("renders a red filled dot for immediate with its aria-label", () => {
    render(<TierMarker tier="immediate" />);
    const marker = screen.getByLabelText("Immediate service need");
    expect(marker).toHaveClass("bg-alert");
  });

  it("renders an orange filled dot for urgent with its aria-label", () => {
    render(<TierMarker tier="urgent" />);
    const marker = screen.getByLabelText("Urgent service need");
    expect(marker).toHaveClass("bg-warning");
    expect(marker).not.toHaveClass("border-2");
  });

  it("renders a yellow filled dot for standard with its aria-label", () => {
    render(<TierMarker tier="standard" />);
    const marker = screen.getByLabelText("Standard service need");
    expect(marker).toHaveClass("bg-[#facc15]");
  });

  it("still renders the marker when a narration tooltip is given", () => {
    render(<TierMarker tier="immediate" narration="Disk full soon" />);
    expect(screen.getByLabelText("Immediate service need")).toBeInTheDocument();
  });
});
