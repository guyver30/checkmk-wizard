# Quick Task 261001-s0c: wizard --demo mode (fake hosts in a subnet, no scanning) - Context

**Gathered:** 2026-10-01
**Status:** Ready for planning

<domain>
## Task Boundary

Add a `--demo` flag to `checkmk-wizard`. In demo mode, Phase 3 does NOT scan the
network; instead it generates a given number of host IPs inside a given subnet and
feeds them to Phase 4 as if they had been scanned. Every other phase (1, 2, 4, 5, 6, 7)
runs unchanged. Because the hosts do not exist on the network they would show DOWN,
so after Phase 7 activation the wizard fakes them UP via Livestatus external commands.

User's original snippet (reference only — do NOT use podman exec):
  cmk() { podman exec checkmk su - dmc -c "lq 'COMMAND [$(date +%s)] $1'"; }
  cmk "DISABLE_HOST_CHECK;host_ip"
  cmk "PROCESS_HOST_CHECK_RESULT;host_ip;1;faked up"
Note: state 1 = DOWN; the user's intent is UP, so use state 0.
</domain>

<decisions>
## Implementation Decisions

### End state of demo hosts — "All UP"
- After Phase 7 activation (hosts must exist in the core first), for each demo host send:
  - `DISABLE_HOST_CHECK;<host>` then `PROCESS_HOST_CHECK_RESULT;<host>;0;faked up`
  - Also fake the auto-created `PING` active service so it is not CRIT:
    `DISABLE_SVC_CHECK;<host>;PING` then `PROCESS_SERVICE_CHECK_RESULT;<host>;PING;0;faked up`
- `<host>` is the Checkmk host NAME chosen in Phase 4 (defaults to the IP), not necessarily the IP.
- Send commands over Livestatus TCP (port 6557, same as `livestatus.query_host_states`),
  format `COMMAND [<unix ts>] <cmd>\n\n` — NOT podman exec (container-boundary constraint).
  Add a small `send_commands(host, commands, port)` to `livestatus.py`.
- Best-effort: failure prints a yellow warning with the manual commands, never aborts.

### Input — flag + prompts
- `checkmk-wizard --demo` (argparse in `main()`; also pass through `run(demo=...)`).
- In demo mode Phase 3 prompts for host count and subnet per Phase 2 folder that has a
  subnet (subnet default = the folder's subnet); with no folders, one prompt pair into root,
  subnet default `198.51.100.0/24` (TEST-NET-2, non-routable).
- Generated IPs: the first N usable host addresses of the subnet, skipping IPs already
  known in Checkmk; validate count fits.
- Print a clear banner that demo mode is active and no scanning happens.

### Classification — keep Phase 4 prompts
- Phase 4 prompts stay as today (operator names and classifies each host).
- In demo mode, the "Monitoring method" select defaults to `ping` (to avoid SSH/agent
  waits on nonexistent hosts); operator may still pick another.
- Faking in Phase 7 applies to all hosts onboarded this run in demo mode.

### Claude's Discretion
- Exact plumbing of the demo flag through phase functions (keyword-only arg with default False
  so existing callers/tests are unaffected).
- Whether the PING faking is skipped for non-ping hosts (fine to send anyway; unknown
  service commands are harmless).
</decisions>

<specifics>
## Specific Ideas
- Tests: argparse flag, demo IP generation (count, skip known, overflow), phase3 demo path does
  not call the scanner, livestatus send_commands wire format, phase7 sends commands only in demo.
- Docs: update README / docs for the `--demo` flag (user CLAUDE.md requires docs updates).
- Memory note: fresh 2.4 sites may have LIVESTATUS_TCP_TLS on; the wizard already turns it off.
</specifics>

<canonical_refs>
## Canonical References
- Nagios/Checkmk external commands: DISABLE_HOST_CHECK, PROCESS_HOST_CHECK_RESULT (0 UP/1 DOWN/2 UNREACH),
  DISABLE_SVC_CHECK, PROCESS_SERVICE_CHECK_RESULT; Livestatus COMMAND header format.
</canonical_refs>
