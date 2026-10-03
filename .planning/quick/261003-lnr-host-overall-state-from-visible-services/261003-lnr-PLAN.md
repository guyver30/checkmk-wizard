# Quick 261003-lnr: host overall state from visible services only

Live finding 2026-10-03: a Linux agent host showed CRIT in the tree, map and details because of Checkmk's
"Systemd Timesyncd Time" check, which the dashboard never lists. Operator decision (option 2): hidden services
must not alter the host's overall status.

1. Poller: `apply_visible_service_state()` recomputes an agent host's state from the dashboard-visible services
   (mirrors `agentDetail.ts` plus gauge services, `Check_MK`, `Uptime`); called at the top of `run_cycle`.
2. Tests in `tests/test_mqtt_poller.py`.
3. Document the rule in the Podman setup doc's status-topic section.
