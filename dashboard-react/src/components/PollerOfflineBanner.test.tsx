import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PollerOfflineBanner } from "./PollerOfflineBanner";
import { formatClock } from "../lib/display";
import { useAppStore } from "../store/useAppStore";

const INITIAL_STATE = useAppStore.getState();
const NOW = Date.parse("2026-10-12T12:00:00Z");

function encode(value: unknown): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(value));
}

function publishPoller(payload: unknown) {
  useAppStore.getState().handleMessage("lan/poller/status", encode(payload));
}

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
  useAppStore.getState().setConnection({ phase: "connected" });
});

afterEach(cleanup);

describe("PollerOfflineBanner", () => {
  it("renders nothing before the first poller status has arrived", () => {
    render(<PollerOfflineBanner nowMs={NOW} />);
    expect(screen.queryByTestId("poller-offline-banner")).not.toBeInTheDocument();
  });

  it("renders nothing for an online poller with a fresh last_poll", () => {
    publishPoller({ status: "online", last_poll: "2026-10-12T11:59:30Z" });
    render(<PollerOfflineBanner nowMs={NOW} />);
    expect(screen.queryByTestId("poller-offline-banner")).not.toBeInTheDocument();
  });

  it("shows the offline wording with the last_poll clock time when the will fired", () => {
    publishPoller({ status: "offline", last_poll: "2026-10-12T11:50:00Z" });
    render(<PollerOfflineBanner nowMs={NOW} />);
    expect(
      screen.getByText(
        `Poller offline since ${formatClock("2026-10-12T11:50:00Z")} — device states may be out of date`,
      ),
    ).toBeInTheDocument();
  });

  it("falls back to the last known poller timestamp when the will payload has none", () => {
    publishPoller({ status: "online", last_poll: "2026-10-12T11:55:00Z" });
    publishPoller({ status: "offline" });
    render(<PollerOfflineBanner nowMs={NOW} />);
    expect(
      screen.getByText(new RegExp(`offline since ${formatClock("2026-10-12T11:55:00Z")}`)),
    ).toBeInTheDocument();
  });

  it("shows the has-not-reported wording for an online poller whose last_poll is stale", () => {
    publishPoller({ status: "online", last_poll: "2026-10-12T11:00:00Z" });
    render(<PollerOfflineBanner nowMs={NOW} />);
    expect(
      screen.getByText(
        `Poller has not reported since ${formatClock("2026-10-12T11:00:00Z")} — device states may be out of date`,
      ),
    ).toBeInTheDocument();
  });

  it("is suppressed while the MQTT connection is down", () => {
    publishPoller({ status: "offline", last_poll: "2026-10-12T11:50:00Z" });
    useAppStore.getState().setConnection({ phase: "reconnecting", delayMs: 2000 });
    render(<PollerOfflineBanner nowMs={NOW} />);
    expect(screen.queryByTestId("poller-offline-banner")).not.toBeInTheDocument();
  });
});
