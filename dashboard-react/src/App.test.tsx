import { render, screen } from "@testing-library/react";
import { Badge } from "kone-design-system";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App";
import { DetailsRoute } from "./routes/DetailsRoute";

describe("App", () => {
  afterEach(() => {
    window.history.pushState({}, "", "/");
  });

  it("renders the three-pane layout at /", () => {
    render(<App />);
    expect(screen.getByTestId("topology-map")).toBeInTheDocument();
  });

  it("enters kiosk mode at /?kiosk=1, with no NavBar", () => {
    window.history.pushState({}, "", "/?kiosk=1");
    render(<App />);
    expect(screen.getByText("Incidents")).toBeInTheDocument();
    expect(screen.queryByText("DMC digital live dashboard")).not.toBeInTheDocument();
  });

  it("renders the normal app at / with the NavBar present", () => {
    render(<App />);
    expect(screen.getByText("DMC digital live dashboard")).toBeInTheDocument();
  });

  it("renders the normal app at /?kiosk=0", () => {
    window.history.pushState({}, "", "/?kiosk=0");
    render(<App />);
    expect(screen.getByText("DMC digital live dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("topology-map")).toBeInTheDocument();
  });

  it("renders the normal app at /details?kiosk=1", () => {
    window.history.pushState({}, "", "/details?kiosk=1");
    render(<App />);
    expect(screen.getByText("DMC digital live dashboard")).toBeInTheDocument();
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
