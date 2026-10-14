import { render, screen, within } from "@testing-library/react";
import { Badge } from "kone-design-system";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";
import App, { AppShell } from "./App";
import { __setRuntimeConfigForTests } from "./lib/runtimeConfig";

describe("App", () => {
  afterEach(() => {
    window.history.pushState({}, "", "/");
    __setRuntimeConfigForTests();
  });

  it("shows the SEN next to the site id when siteSen is configured", () => {
    __setRuntimeConfigForTests({ siteSen: "123" });
    render(<App />);
    expect(within(screen.getByRole("banner")).getByTestId("site-sen")).toHaveTextContent("SEN 123");
  });

  it("renders no SEN element when siteSen is absent", () => {
    render(<App />);
    expect(within(screen.getByRole("banner")).queryByTestId("site-sen")).not.toBeInTheDocument();
  });

  it("renders the three-pane layout at /", () => {
    render(<App />);
    expect(screen.getByTestId("topology-map")).toBeInTheDocument();
  });

  it("shows the fleet state summary as compact badges in the header next to Home", () => {
    render(<App />);
    const banner = screen.getByRole("banner");
    const status = within(banner).getByRole("status", { name: /fleet state summary/i });
    expect(status).toHaveTextContent("OK 0");
  });

  it("labels the main link Home and shows the Checkmk site id before the state badges", () => {
    render(<App />);
    const banner = screen.getByRole("banner");
    expect(within(banner).getByText("Home")).toBeInTheDocument();
    expect(within(banner).queryByText("Overview")).not.toBeInTheDocument();
    const site = within(banner).getByTestId("site-id");
    const status = within(banner).getByRole("status", { name: /fleet state summary/i });
    expect(site).toHaveTextContent(/\S/);
    // The site id comes before the state badges in document order.
    expect(site.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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
