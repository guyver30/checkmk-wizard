import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TierMarker } from "./TierMarker";

describe("TierMarker", () => {
  it("renders nothing for standard", () => {
    const { container } = render(<TierMarker tier="standard" narration="x" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a filled dot for immediate with its aria-label", () => {
    render(<TierMarker tier="immediate" />);
    const marker = screen.getByLabelText("Immediate service need");
    expect(marker).toHaveClass("bg-warning");
  });

  it("renders a ring for urgent with its aria-label", () => {
    render(<TierMarker tier="urgent" />);
    const marker = screen.getByLabelText("Urgent service need");
    expect(marker).toHaveClass("border-2", "border-warning");
    expect(marker).not.toHaveClass("bg-warning");
  });

  it("still renders the marker when a narration tooltip is given", () => {
    render(<TierMarker tier="immediate" narration="Disk full soon" />);
    expect(screen.getByLabelText("Immediate service need")).toBeInTheDocument();
  });
});
