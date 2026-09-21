import { render, screen } from "@testing-library/react";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import mqtt from "mqtt";
import { ConnectionIndicator } from "./ConnectionIndicator";
import App from "../App";
import { __resetForTests } from "../store/mqttClient";
import { useAppStore } from "../store/useAppStore";

// Real mqtt.js would open an actual WebSocket from a browser/jsdom environment -- mocked here
// so the "connect exactly once" assertion below exercises mqttClient.ts's own StrictMode
// idempotency guard (plan 05's module-level `client` singleton) rather than a real network call.
vi.mock("mqtt", () => {
  const fakeClient = {
    on: vi.fn().mockReturnThis(),
    subscribe: vi.fn(),
    reconnect: vi.fn(),
    end: vi.fn(),
  };
  return { default: { connect: vi.fn(() => fakeClient) } };
});

const INITIAL_STATE = useAppStore.getState();

beforeEach(() => {
  useAppStore.setState(INITIAL_STATE, true);
  __resetForTests();
});

describe("ConnectionIndicator", () => {
  it("renders StatusBadge status connected with the text Connected", () => {
    useAppStore.getState().setConnection({ phase: "connected" });
    render(<ConnectionIndicator />);
    expect(screen.getByText("Connected")).toBeInTheDocument();
  });

  it("renders status low-signal with the retry delay in seconds, taken from the store", () => {
    useAppStore.getState().setConnection({ phase: "reconnecting", delayMs: 4200 });
    render(<ConnectionIndicator />);
    expect(screen.getByText(/4s/)).toBeInTheDocument();
  });

  it("renders status entrapment with the text Disconnected", () => {
    useAppStore.getState().setConnection({ phase: "disconnected" });
    render(<ConnectionIndicator />);
    expect(screen.getByText("Disconnected")).toBeInTheDocument();
  });

  it("renders status unknown with the text Connecting…", () => {
    useAppStore.getState().setConnection({ phase: "connecting" });
    render(<ConnectionIndicator />);
    expect(screen.getByText("Connecting…")).toBeInTheDocument();
  });

  it("exposes its text to assistive technology via role=status", () => {
    useAppStore.getState().setConnection({ phase: "connected" });
    render(<ConnectionIndicator />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

describe("App mount", () => {
  it("connects exactly once even under StrictMode's double-invoked effects", () => {
    render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
    // Mounting under StrictMode runs the effect body (and therefore calls connect()) twice --
    // this asserts mqttClient.ts's own singleton guard collapses that into a single real
    // connection attempt, not that App's effect body itself only runs once.
    expect(mqtt.connect).toHaveBeenCalledTimes(1);
  });
});
