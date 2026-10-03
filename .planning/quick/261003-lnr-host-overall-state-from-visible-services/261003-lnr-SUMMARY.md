---
status: complete
---
# Quick 261003-lnr summary

Agent hosts (those with a `Check_MK Agent` service) now take their overall state from the worst dashboard-visible
service (Checkmk order OK < WARN < UNKNOWN < CRIT); DOWN/UNREACHABLE hosts and non-agent hosts are unchanged.
Applied in `run_cycle` before status, events, history, topology and incidents read `snapshot.state`.
Tests: 23 new cases; full suite 823 passed; ruff clean.

Not verified live. Known gap: on a cycle whose services query fails, the host-column state is published as before,
so a host with a hidden non-OK service can briefly flip back to CRIT (and log a state_change event) until the next
good cycle. The poller image must be rebuilt and the poller recreated with a full compose down/up to deploy.
