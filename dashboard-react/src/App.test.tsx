import { render, screen } from "@testing-library/react";
import { Badge } from "kone-design-system";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import App, { AppShell } from "./App";

describe("App", () => {
  afterEach(() => {
    window.history.pushState({}, "", "/");
  });

  it("renders the three-pane layout at /", () => {
    render(<App />);
    expect(screen.getByTestId("topology-map")).toBeInTheDocument();
  });

  it("renders the normal app at / with the NavBar present", () => {
    render(<App />);
    expect(screen.getByText("DMC digital live dashboard")).toBeInTheDocument();
  });

  it("redirects a bookmarked /details?id=<id> link to the /?host=<id> pane", () => {
    render(
      <MemoryRouter initialEntries={["/details?id=sw-edge-01"]}>
        <AppShell />
      </MemoryRouter>,
    );
    // The pane shows the locked "Device not found" copy (the store has no matching device
    // here), which still echoes the id back as text.
    expect(screen.getByText("Device not found")).toBeInTheDocument();
    // Echoed in the pane and in the event history's host filter line, hence getAll.
    expect(screen.getAllByText(/sw-edge-01/).length).toBeGreaterThan(0);
  });

  it("/details with no id redirects to / with no 'Device not found' pane", () => {
    render(
      <MemoryRouter initialEntries={["/details"]}>
        <AppShell />
      </MemoryRouter>,
    );
    expect(screen.queryByText("Device not found")).not.toBeInTheDocument();
  });

  it("renders a design-system Badge with the library's own compiled styles applied", () => {
    render(<Badge>connected</Badge>);
    expect(screen.getByText("connected").className).toContain("rounded-pill");
  });
});
