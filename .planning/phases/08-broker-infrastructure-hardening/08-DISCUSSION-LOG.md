# Phase 8: Broker Infrastructure Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the discussion.

**Date:** 2026-09-05
**Phase:** 08-broker-infrastructure-hardening
**Mode:** discuss (interactive)
**Areas discussed:** Config artifact location, 1883 TCP listener exposure, Verification approach, ACL credential handling

## Area Selection

Presented 4 gray areas (all selected by user):
- Config artifact location
- 1883 TCP listener exposure
- Verification approach
- ACL credential handling

## Config Artifact Location

**Q1: Where should Phase 8's mosquitto.conf / compose.yaml / ACL files actually live?**
- Options: Check real files into repo (new deploy/ dir) [recommended] / Docs-only (current pattern) / Both — real files + doc update
- Selected: **Both — real files + doc update**

**Q2: Should the repo's new deploy/compose.yaml be the full 4-service stack or just the mosquitto/broker piece?**
- Options: Full stack (all 4 services) [recommended] / Broker-only fragment
- Selected: **Full stack (all 4 services)**

## 1883 TCP Listener Exposure

**Q1: Should the existing 1883 TCP listener be tightened in this phase, alongside adding the ACL'd WS listener?**
- Options: Tighten it now (recommended by PITFALLS.md) / Leave as-is
- Selected (via free text): "I still want to have 1883 exposed to the outside for debugging, but later on I want to keep it only internal" — interpreted as: keep 1883 published to the LAN this phase, defer internal-only restriction to a future pass.

**Q2 (follow-up): Since 1883 stays LAN-published, should it also get authentication now?**
- Options: Stay anonymous, unrestricted (defer everything) [recommended given framing] / Add authentication to 1883 now, keep it published
- Selected: **Add authentication to 1883 now, keep it published**

## Verification Approach

**Q1: How should Phase 8's runtime success criteria be verified?**
- Options: Automated smoke-test script [recommended] / Manual runbook only
- Selected: **Automated smoke-test script**

**Q2 (follow-up): Add paho-mqtt as a dependency now, or keep the script dependency-free?**
- Options: Add paho-mqtt now via uv add [recommended] / Keep dependency-free (CLI/subprocess-based)
- Selected: **Add paho-mqtt now via uv add**

## ACL Credential Handling

**Q1: How should the mosquitto password_file be created and checked in?**
- Options: Checked-in pre-hashed file with documented default creds [recommended] / Generated at deploy time via a setup script
- Selected: **Checked-in pre-hashed file with documented default creds**

## Deferred Ideas

- Restricting 1883 to container-internal-only network reachability — user wants it LAN-reachable for debugging now, to be tightened in a later hardening pass.

## Claude's Discretion (noted, not asked)

- Exact ACL topic patterns, username naming, password-hash generation method, smoke-test script location, `deploy/` internal layout.
