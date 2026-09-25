// Splits a host's published service rows into the four things the agent-host detail view
// shows (2026-09-25): agent connection, uptime, the services chosen in the wizard, and the
// monitored TCP ports. Pure function -- no DOM, store or network access.
//
// The service descriptions below are Checkmk 2.4's own default names ("Check_MK Agent",
// "Check_MK", "Uptime", "Systemd Service <unit>", "Service <name>") plus the wizard's
// "TCP Port <N> (expected open)" (wizard.py `_create_expected_open_port_rules`). They were
// NOT live-verified against a running site; if a site names them differently only these
// constants need to change.

import type { ServiceEntry } from "./types";

// Present only on hosts monitored through the Checkmk agent -- what marks a host as an
// "agent host" (an SNMP/ping host has no such service).
export const AGENT_INFO_SERVICE = "Check_MK Agent";
// The agent-connection check: OK when the core got data from the agent on its last fetch.
export const AGENT_CONNECTION_SERVICE = "Check_MK";
export const UPTIME_SERVICE = "Uptime";

// The wizard's discovery rule (`discovery_systemd_units_services` / Windows services) only
// lets the operator's chosen units/services through, so every such row was chosen in the
// wizard. The summary row is Checkmk's own aggregate, not a chosen service.
const CHOSEN_SERVICE_RE = /^(Systemd Service|Service) (?!Summary$)/;
const SYSTEMD_SUMMARY = "Systemd Service Summary";
const TCP_PORT_RE = /^TCP Port \d+/;

export interface AgentServiceView {
  isAgentHost: boolean;
  /** true = connection check OK, false = any other state, null = check not published. */
  agentConnected: boolean | null;
  uptime: ServiceEntry | undefined;
  chosenServices: ServiceEntry[];
  tcpPorts: ServiceEntry[];
}

export function classifyAgentServices(services: ServiceEntry[]): AgentServiceView {
  const byDescription = (description: string) => services.find((s) => s.description === description);
  const connection = byDescription(AGENT_CONNECTION_SERVICE);
  return {
    isAgentHost: byDescription(AGENT_INFO_SERVICE) !== undefined,
    agentConnected: connection === undefined ? null : connection.state === "OK",
    uptime: byDescription(UPTIME_SERVICE),
    chosenServices: services.filter(
      (s) =>
        typeof s.description === "string" &&
        s.description !== SYSTEMD_SUMMARY &&
        CHOSEN_SERVICE_RE.test(s.description),
    ),
    tcpPorts: services.filter((s) => typeof s.description === "string" && TCP_PORT_RE.test(s.description)),
  };
}
