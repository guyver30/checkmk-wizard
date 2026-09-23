import { render, screen } from "@testing-library/react";
import { Badge } from "kone-design-system";
import { MemoryRouter, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";
import App from "./App";
import { DetailsRoute } from "./routes/DetailsRoute";

describe("App", () => {
  it("renders the three-pane layout at /", () => {
    render(<App />);
    expect(screen.getByText("Topology map — Phase 13")).toBeInTheDocument();
  });

  it("reads the hostname from the ?id= query string on /details", () => {
    render(
      <MemoryRouter initialEntries={["/details?id=sw-edge-01"]}>
        <Routes>
          <Route path="/details" element={<DetailsRoute />} />
        </Routes>
      </MemoryRouter>,
    );
    // Plan 12-04 replaced the bare-id stub with the locked "Device not found" copy (the
    // store has no matching device here), which still echoes the id back as text.
    expect(screen.getByText(/sw-edge-01/)).toBeInTheDocument();
  });

  it("renders a design-system Badge with the library's own compiled styles applied", () => {
    render(<Badge>connected</Badge>);
    expect(screen.getByText("connected").className).toContain("rounded-pill");
  });
});
