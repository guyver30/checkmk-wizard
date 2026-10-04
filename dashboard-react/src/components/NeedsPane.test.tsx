import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { NeedsPane, NeedsSummary } from "./NeedsPane";
import { hostHref } from "../lib/searchLinks";
import type { NeedPayload } from "../lib/types";

const NOW_MS = Date.parse("2026-10-04T12:00:00Z");

function need(overrides: Partial<NeedPayload> & { id: string }): NeedPayload {
  return {
    source: "trend",
    host: "srv-a",
    service: "Filesystem /",
    metric: "fs_used_percent",
    unit: "%",
    tier: "urgent",
    computed_tier: "urgent",
    days_to_warn: 10,
    days_to_crit: 30,
    warn_date: "2026-10-14T00:00:00Z",
    crit_date: "2026-11-03T00:00:00Z",
    confidence: "high",
    history_days: 21,
    value: 70,
    warn: 80,
    crit: 90,
    sustained_fraction: null,
    window_hours: null,
    since: "",
    narration: "",
    triage: null,
    generated_at: new Date(NOW_MS).toISOString(),
    ...overrides,
  };
}

function renderPane(props: Partial<React.ComponentProps<typeof NeedsPane>> = {}) {
  const defaults: React.ComponentProps<typeof NeedsPane> = {
    needs: [],
    nameFor: (id) => id,
    nowMs: NOW_MS,
    highlightedHost: null,
    editMode: false,
    updatedAtMs: NOW_MS,
    reconnecting: false,
  };
  return render(
    <MemoryRouter>
      <NeedsPane {...defaults} {...props} />
    </MemoryRouter>,
  );
}

describe("NeedsPane", () => {
  it("renders a labelled region with the title and a count", () => {
    renderPane({ needs: [need({ id: "n1" }), need({ id: "n2", host: "srv-b" })] });
    const region = screen.getByRole("region", { name: "Service needs" });
    expect(within(region).getByText("Service needs")).toBeInTheDocument();
    expect(within(region).getByText("2")).toBeInTheDocument();
  });

  it("renders rows in the order given without re-sorting", () => {
    renderPane({
      needs: [
        need({ id: "standard-first", tier: "standard", host: "zzz" }),
        need({ id: "immediate-second", tier: "immediate", host: "aaa" }),
      ],
    });
    const rows = document.querySelectorAll("[data-need-id]");
    expect(rows[0]).toHaveAttribute("data-need-id", "standard-first");
    expect(rows[0]).toHaveAttribute("data-tier", "standard");
    expect(rows[1]).toHaveAttribute("data-need-id", "immediate-second");
  });

  it("shows the empty state", () => {
    renderPane();
    expect(screen.getByText("No service needs")).toBeInTheDocument();
    expect(
      screen.getByText("Nothing is predicted to cross a limit within 90 days, and no service is failing."),
    ).toBeInTheDocument();
  });

  it("filters by tier and shows the filtered-empty state", () => {
    renderPane({ needs: [need({ id: "n1", tier: "urgent" })] });
    fireEvent.click(screen.getByText("Immediate", { selector: "button *, button" }));
    expect(screen.getByText("No immediate needs")).toBeInTheDocument();
    expect(screen.getByText("Switch the filter to All to see the others.")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Urgent", { selector: "button *, button" }));
    expect(document.querySelector('[data-need-id="n1"]')).not.toBeNull();
  });

  it("trend rows show the crit date and a confidence badge with the history span", () => {
    renderPane({ needs: [need({ id: "n1", confidence: "low", history_days: 9 })] });
    expect(screen.getByText(/Critical by 3 Nov/)).toBeInTheDocument();
    expect(screen.getByText("Confidence: low")).toBeInTheDocument();
    expect(screen.getByText("9 days of history")).toBeInTheDocument();
    expect(screen.getByText(/Critical by/)).toHaveClass("text-fg-secondary");
  });

  it("adds the year to the date when it differs from the current year", () => {
    renderPane({ needs: [need({ id: "n1", crit_date: "2027-01-05T00:00:00Z" })] });
    expect(screen.getByText(/Critical by 5 Jan 2027/)).toBeInTheDocument();
  });

  it("failure rows have no confidence badge and show 'Down since' for a host", () => {
    renderPane({
      needs: [
        need({
          id: "f1",
          source: "failure",
          service: "",
          metric: "",
          confidence: null,
          history_days: null,
          since: "2026-10-04T10:15:00Z",
        }),
      ],
    });
    expect(screen.getByText(/Down since \d\d:\d\d/)).toBeInTheDocument();
    expect(screen.getByText("Failing now")).toBeInTheDocument();
    expect(screen.queryByText(/Confidence:/)).toBeNull();
  });

  it("failure rows for a service say 'Failing since'", () => {
    renderPane({
      needs: [need({ id: "f1", source: "failure", confidence: null, since: "2026-10-04T10:15:00Z" })],
    });
    expect(screen.getByText(/Failing since \d\d:\d\d/)).toBeInTheDocument();
  });

  it("sustained rows show the duration from window hours and fraction", () => {
    renderPane({
      needs: [
        need({ id: "s1", source: "sustained", confidence: null, window_hours: 24, sustained_fraction: 0.75 }),
      ],
    });
    expect(screen.getByText("Critical for 18 h")).toBeInTheDocument();
    expect(screen.getByText("Over limit for 18 h")).toBeInTheDocument();
  });

  it("the row is a link carrying the host query parameter", () => {
    renderPane({ needs: [need({ id: "n1", host: "srv-a" })] });
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", hostHref("", "srv-a"));
    expect(link.getAttribute("href")).toContain("host=srv-a");
  });

  it("marks the row of the highlighted host", () => {
    renderPane({ needs: [need({ id: "n1" }), need({ id: "n2", host: "srv-b" })], highlightedHost: "srv-b" });
    const links = screen.getAllByRole("link");
    expect(links[0]).not.toHaveAttribute("aria-current");
    expect(links[1]).toHaveAttribute("aria-current", "true");
    expect(links[1].className).toContain("bg-brand-light");
  });

  it("shows the narration verbatim as text in a tooltip on hover", () => {
    renderPane({ needs: [need({ id: "n1", narration: "Disk <b>fills</b> in 30 days." })] });
    fireEvent.mouseEnter(screen.getByRole("link").parentElement as HTMLElement);
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("Disk <b>fills</b> in 30 days.");
    expect(tip.querySelector("b")).toBeNull();
  });

  it("shows 'Updated' when fresh and 'Stale, last update' after 45 minutes", () => {
    const { unmount } = renderPane({ updatedAtMs: NOW_MS - 5 * 60 * 1000 });
    expect(screen.getByRole("status")).toHaveTextContent(/^Updated \d\d:\d\d$/);
    unmount();
    renderPane({ updatedAtMs: NOW_MS - 46 * 60 * 1000 });
    expect(screen.getByRole("status")).toHaveTextContent(/^Stale, last update \d\d:\d\d$/);
  });

  it("dims rows and says 'Reconnecting' while reconnecting", () => {
    renderPane({ needs: [need({ id: "n1" })], reconnecting: true });
    expect(screen.getByRole("status")).toHaveTextContent("Reconnecting");
    expect(screen.getByRole("link").className).toContain("opacity-60");
  });

  it("shows a caption for a triaged need with the effective tier", () => {
    renderPane({
      needs: [
        need({
          id: "n1",
          tier: "standard",
          computed_tier: "urgent",
          triage: {
            action: "downgrade",
            tier: "standard",
            set_at: "2026-10-04T09:30:00Z",
            computed_tier_at_set: "urgent",
            note: "",
            by: "Ann",
          },
        }),
      ],
    });
    expect(screen.getByText(/Downgraded from urgent by Ann, \d\d:\d\d/)).toBeInTheDocument();
    expect(within(screen.getByRole("link")).getByText("Standard")).toBeInTheDocument();
  });

  it("omits 'by' from the triage caption when no name is recorded", () => {
    renderPane({
      needs: [
        need({
          id: "n1",
          tier: "immediate",
          triage: {
            action: "upgrade",
            tier: "immediate",
            set_at: "2026-10-04T09:30:00Z",
            computed_tier_at_set: "urgent",
            note: "",
            by: "",
          },
        }),
      ],
    });
    expect(screen.getByText(/^Upgraded from urgent, \d\d:\d\d$/)).toBeInTheDocument();
  });
});

describe("NeedsPane edit mode and chart entry", () => {
  it("shows the Triage menu only in edit mode", () => {
    const { unmount } = renderPane({ needs: [need({ id: "n1" })], editMode: false });
    expect(screen.queryByRole("button", { name: "Triage" })).toBeNull();
    unmount();
    renderPane({ needs: [need({ id: "n1" })], editMode: true });
    expect(screen.getByRole("button", { name: "Triage" })).toBeInTheDocument();
  });

  it("shows View chart only for trend needs and opens the forecast dialog", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 500 })));
    renderPane({
      needs: [
        need({ id: "t1", host: "srv-t" }),
        need({ id: "f1", host: "srv-f", source: "failure", confidence: null, since: "2026-10-04T10:15:00Z" }),
      ],
    });
    const buttons = screen.getAllByRole("button", { name: "View chart" });
    expect(buttons).toHaveLength(1);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(buttons[0]);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

describe("NeedsSummary", () => {
  it("shows the count and the worst tier", () => {
    render(
      <NeedsSummary needs={[need({ id: "a", tier: "standard" }), need({ id: "b", tier: "immediate" })]} />,
    );
    const summary = screen.getByTestId("needs-severity");
    expect(summary).toHaveAttribute("data-tier", "immediate");
    expect(summary).toHaveTextContent("2");
    expect(summary).toHaveTextContent("Immediate");
  });

  it("shows a quiet 0 when empty", () => {
    render(<NeedsSummary needs={[]} />);
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.queryByTestId("needs-severity")).toBeNull();
  });
});
