// Display naming, state/icon classification and relative-time formatting for one device
// payload. Every function tolerates a payload that predates plan 11-01 (no `staleness`, no
// `host_state_raw` key) or is otherwise malformed, returning a safe default instead of
// throwing -- the same defensive-parse posture query_devices() applies per-column in
// scripts/mqtt_poller.py.
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only.

import type { DevicePayload } from "./types";

export function displayName(devicePayload: DevicePayload | null | undefined): string {
  // D-18: alias when non-empty after trimming, otherwise the hostname (`id`). The wizard's
  // Phase 4/10.1 alias prompt exists precisely so an operator can give a host a human name.
  if (!devicePayload || typeof devicePayload !== "object") {
    return "";
  }
  const alias = typeof devicePayload.alias === "string" ? devicePayload.alias.trim() : "";
  if (alias) {
    return alias;
  }
  return typeof devicePayload.id === "string" ? devicePayload.id : "";
}

export function displayAddress(devicePayload: DevicePayload | null | undefined): string {
  // OD-1/OD-2 (quick 260928-m6f): the host's IP, but only when it differs from the
  // displayed name -- an IP-named host with no alias would otherwise show its own IP
  // twice. Empty/missing/non-string address (unmanaged switch, or a payload from an
  // older poller) degrades to "", same defensive-parse posture as displayName above.
  if (!devicePayload || typeof devicePayload !== "object") {
    return "";
  }
  const address = typeof devicePayload.address === "string" ? devicePayload.address.trim() : "";
  if (!address || address === displayName(devicePayload)) {
    return "";
  }
  return address;
}

export function displayNameWithAddress(devicePayload: DevicePayload | null | undefined): string {
  // OD-4: `name (ip)` wherever displayAddress is non-empty, otherwise displayName unchanged.
  const name = displayName(devicePayload);
  const address = displayAddress(devicePayload);
  return address ? `${name} (${address})` : name;
}

export function effectiveState(devicePayload: DevicePayload | null | undefined): string {
  // Pitfall 6 (11-RESEARCH.md): `state` structurally cannot contain "UNREACH" --
  // compute_overall_state() in scripts/mqtt_poller.py deliberately collapses raw host
  // states 1 (DOWN) and 2 (UNREACHABLE) into a single "DOWN" string. Reading `state` alone
  // would leave the UNREACH branch permanently dead; `host_state_raw` is the only field
  // that can ever legitimately read "UNREACH" (D-17).
  if (!devicePayload || typeof devicePayload !== "object") {
    return "UNKNOWN";
  }
  if (devicePayload.host_state_raw === "UNREACH") {
    return "UNREACH";
  }
  return typeof devicePayload.state === "string" ? devicePayload.state : "UNKNOWN";
}

export function stateClass(state: string | null | undefined): string {
  const known = new Set(["ok", "warn", "crit", "down", "unknown", "unreach", "pend"]);
  const normalised = typeof state === "string" ? state.toLowerCase() : "";
  return known.has(normalised) ? `state-${normalised}` : "state-unknown";
}

export function stateIcon(state: string | null | undefined): string {
  // Locked icon CLASS NAME strings (UI-SPEC.md "State-color to meaning map"). Never an
  // emoji character -- the pre-KONE Unicode DOWN-marker glyph is superseded by
  // UI-SPEC.md's `.icon-close-circle-filled` mask class.
  const icons: Record<string, string> = {
    OK: "icon-good-filled",
    WARN: "icon-warning-triangle-filled",
    CRIT: "icon-bad-filled",
    DOWN: "icon-close-circle-filled",
    UNKNOWN: "icon-question-circle-filled",
    UNREACH: "icon-status-unavailable",
    PEND: "icon-clock",
  };
  return (state && icons[state]) || icons.UNKNOWN;
}

export function isTagGroupMissing(devicePayload: DevicePayload | null | undefined): boolean {
  // D-16: device_type "unknown" means the Checkmk device_type tag group does not exist on
  // the site at all -- a site-configuration warning, never a device category.
  return !!devicePayload && devicePayload.device_type === "unknown";
}

export function formatRelativeTime(
  isoString: string | null | undefined,
  nowMs: number = Date.now(),
): string {
  // Compact relative string for the Last Update column and the stale tooltip.
  const parsed = Date.parse(isoString ?? "");
  if (Number.isNaN(parsed)) {
    return "unknown"; // neutral placeholder rather than "NaNs ago"
  }
  const diffSeconds = Math.max(0, Math.round((nowMs - parsed) / 1000));
  if (diffSeconds < 60) {
    return `${diffSeconds}s ago`;
  }
  const diffMinutes = Math.round(diffSeconds / 60);
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`;
  }
  const diffHours = Math.round(diffMinutes / 60);
  return `${diffHours}h ago`;
}

export function formatClock(isoString: string | null | undefined): string {
  // D-14's locked banner string wants a plain HH:MM.
  const parsed = Date.parse(isoString ?? "");
  if (Number.isNaN(parsed)) {
    return "unknown";
  }
  const date = new Date(parsed);
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

export function formatDateTime(isoString: string | null | undefined): string {
  // Local YYYY-MM-DD HH:MM:SS: year-first order is unambiguous across locales (toLocaleString
  // flips D/M vs M/D), and local time matches formatClock's existing choice.
  const parsed = Date.parse(isoString ?? "");
  if (Number.isNaN(parsed)) {
    return "unknown";
  }
  const date = new Date(parsed);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())} ${p(date.getHours())}:${p(date.getMinutes())}:${p(date.getSeconds())}`;
}
