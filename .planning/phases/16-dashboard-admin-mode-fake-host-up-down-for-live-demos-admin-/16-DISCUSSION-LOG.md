# Phase 16: Dashboard admin mode for live demos - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-10-02
**Phase:** 16-dashboard-admin-mode-for-live-demos
**Areas discussed:** Fake-state semantics, Broker credential and ACL, Persistence and restore, Safety for real hosts

Earlier (before the discuss step, when the phase was added): command path = MQTT to the poller (chosen over a
small nginx-fronted service); gate = `?admin=1` query flag (chosen over a passphrase or a separate URL);
process = new phase with a discuss step (chosen over one big quick task).

---

## Fake-state semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-cascade UNREACHABLE | Descendants of a DOWN managed parent become UNREACHABLE | yes |
| Checkbox in the action bar | Same cascade, optional | |
| No cascade | Only selected hosts change | |

**User's choice:** Auto-cascade UNREACHABLE.

| Option | Description | Selected |
|--------|-------------|----------|
| Fake its children DOWN | Switch stays UP; children DOWN; inferred-root rule builds the card | |
| Do nothing on the switch | DOWN ignored for unmanaged switches | |
| Other (free text) | "when I send down to all its children, there needs to be the inferred-root rule to build the combined switch card with children listed" | yes |

**Notes:** Read as: no special switch action; DOWN goes to the children and the existing inferred-root rule
must produce the combined card. The cascade must therefore not push UNREACHABLE through an unmanaged switch.

---

## Broker credential and ACL

| Option | Description | Selected |
|--------|-------------|----------|
| /admin-config.json, limited by network | nginx allow-list from .env | |
| /admin-config.json, open | Anyone reaching the dashboard with the path | yes |
| Always in /config.json | Every viewer receives the login | |

**User's choice:** Separate /admin-config.json, open (closed demo network).

| Option | Description | Selected |
|--------|-------------|----------|
| Ack topic with result | Poller confirms applied/failed | yes |
| Fire and forget | No confirmation | |

**User's choice:** Ack topic with result.

---

## Persistence and restore

| Option | Description | Selected |
|--------|-------------|----------|
| Poller derives it, admin-only topic | From Livestatus, retained, admin-only read | yes |
| Public flag, hidden in the UI | Visible in MQTT/dev tools | |
| Not tracked | Operator remembers | |

**User's choice:** Poller derives it, admin-only topic.

| Option | Description | Selected |
|--------|-------------|----------|
| Until restored | Fake stays until Restore | yes |
| Auto-expire after N minutes | Poller restores by itself | |

**User's choice:** Until restored.

---

## Safety for real hosts

| Option | Description | Selected |
|--------|-------------|----------|
| Any host, with a confirm | Dialog lists action and hosts | yes |
| Only hosts with a demo label | Label-gated | |
| Any host, no confirm | One click | |

**User's choice:** Any host, with a confirm.

| Option | Description | Selected |
|--------|-------------|----------|
| Banner + notification warning | | |
| Banner only | | yes |
| Neither | | |

**User's choice:** Banner only.

## Claude's Discretion

Topic names and payload shape; selection UX details; folder-to-hosts mapping and cascade traversal; keeping
edit mode and admin mode apart; how to reliably derive "faked" from Livestatus (research must verify).

## Deferred Ideas

Auto-expiry; source-network restriction for /admin-config.json; notification warning; criticality model todo.
