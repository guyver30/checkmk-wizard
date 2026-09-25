import { describe, expect, it } from "vitest";
import { classifyAgentServices } from "./agentDetail";
import type { ServiceEntry } from "./types";

const svc = (description: string, state = "OK"): ServiceEntry => ({ description, state, plugin_output: "" });

describe("classifyAgentServices", () => {
  it("marks a host as an agent host only when 'Check_MK Agent' is present", () => {
    expect(classifyAgentServices([svc("Check_MK Agent")]).isAgentHost).toBe(true);
    // An SNMP/ping-style host: connection service but no agent-info service.
    expect(classifyAgentServices([svc("Check_MK"), svc("Uptime")]).isAgentHost).toBe(false);
    expect(classifyAgentServices([]).isAgentHost).toBe(false);
  });

  it("derives agent connectivity from the 'Check_MK' service state", () => {
    expect(classifyAgentServices([svc("Check_MK", "OK")]).agentConnected).toBe(true);
    expect(classifyAgentServices([svc("Check_MK", "CRIT")]).agentConnected).toBe(false);
    expect(classifyAgentServices([svc("Check_MK Agent")]).agentConnected).toBeNull();
  });

  it("returns the uptime row, chosen services and TCP ports, and nothing else", () => {
    const view = classifyAgentServices([
      svc("Check_MK Agent"),
      svc("Check_MK"),
      svc("Check_MK Discovery"),
      svc("Uptime"),
      svc("Systemd Service ssh"),
      svc("Systemd Service open-vm-tools", "WARN"),
      svc("Systemd Service Summary"),
      svc("Service Spooler"),
      svc("TCP Port 22 (expected open)"),
      svc("TCP Port 8000 (expected open)", "CRIT"),
      svc("Interface 2"),
      svc("PING"),
    ]);
    expect(view.uptime?.description).toBe("Uptime");
    expect(view.chosenServices.map((s) => s.description)).toEqual([
      "Systemd Service ssh",
      "Systemd Service open-vm-tools",
      "Service Spooler",
    ]);
    expect(view.tcpPorts.map((s) => s.description)).toEqual([
      "TCP Port 22 (expected open)",
      "TCP Port 8000 (expected open)",
    ]);
  });

  it("skips rows without a string description instead of throwing", () => {
    const view = classifyAgentServices([{ state: "OK" }, { description: 5 as unknown as string }]);
    expect(view.chosenServices).toEqual([]);
    expect(view.tcpPorts).toEqual([]);
  });
});
