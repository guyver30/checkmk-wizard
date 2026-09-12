---
phase: quick-260912-o7n
plan: 01
subsystem: remote-agent-automation
tags: [cmk-agent-ctl, ssh, agent-registration, checkmk-rest-api, ipv6]

requires: []
provides:
  - "Port-aware --server value in linux_register_command/windows_register_command"
  - "Widened registration-address guard covering bare single-label hostnames"
  - "sudo in every printed manual Linux registration instruction"
affects: [remote.py, wizard.py]

tech-stack:
  added: []
  patterns:
    - "Module-private helper (_server_with_receiver_port) appends a well-known default port only when the caller-supplied value doesn't already carry one, disambiguating bare IPv6 literals via ipaddress.ip_address before falling back to rsplit(':', 1)."

key-files:
  created: []
  modified:
    - src/checkmk_wizard/remote.py
    - src/checkmk_wizard/wizard.py
    - tests/test_remote.py
    - tests/test_wizard.py

key-decisions:
  - "Bug 1 fix lives in a single new helper (_server_with_receiver_port) shared by both linux_register_command and windows_register_command, keeping AGENT_RECEIVER_PORT as the sole source of truth rather than making the port configurable (CLAUDE.md simplicity-first)."
  - "Bug 2's guard generalizes _looks_loopback's caller into a new predicate (_unusable_from_remote_target) rather than modifying _looks_loopback itself, since the per-target loopback early-out still needs the narrower check."
  - "Bug 3's sudo is added only to the three printed manual-fallback strings, not to linux_register_command itself, since the automated SSH path already elevates via _run_sudo() and baking sudo into the command string would double-elevate."

requirements-completed: [BUG-1-receiver-port, BUG-2-container-dns-name, BUG-3-missing-sudo]

duration: 15min
completed: 2026-09-12
---

# Quick Task 260912-o7n: Fix Three Agent-Registration Bugs Summary

Fixed three live-diagnosed bugs in the agent-registration path: `cmk-agent-ctl register --server` now always carries an explicit agent-receiver port (bypassing failed REST-API port discovery on non-default REST/GUI ports), container mode's Podman-internal DNS name no longer leaks into a remote target's `--server` value, and every printed manual Linux registration command now includes `sudo` to match what the automated path actually runs.

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-09-12
- **Tasks:** 3/3 (Task 3 was verification-only, no files modified)
- **Files modified:** 4 (`src/checkmk_wizard/remote.py`, `src/checkmk_wizard/wizard.py`, `tests/test_remote.py`, `tests/test_wizard.py`)

## Accomplishments

- `linux_register_command`/`windows_register_command` in `remote.py` now append `AGENT_RECEIVER_PORT` (8000) to `--server` unless the value already carries an explicit port, with correct handling for IPv4, bare IPv6 (`::1` → `[::1]:8000`), and bracketed IPv6-with-port (passed through unchanged).
- `_resolve_agent_registration_server` in `wizard.py` now triggers its existing correction prompt for any bare single-label hostname (not just loopback addresses), catching the container-mode default `checkmk` that no LAN target can resolve.
- All three printed manual Linux registration commands (`register_agent_linux`, `install_agent_linux` step 3, `_print_linux_manual`) now include `sudo`.
- 34 new/updated regression tests added across `tests/test_remote.py` and `tests/test_wizard.py`, each naming the bug it guards per repo convention.

## Task Commits

1. **Task 1: remote.py — append the agent receiver port to --server, and sudo the Linux manual strings** - `05cd5bf` (fix)
2. **Task 2: wizard.py — widen the registration-address guard to bare hostnames, and sudo the printed manual** - `51ffec9` (fix)
3. **Task 3: Full-suite regression check** - verification only, no commit (402 tests passed, ruff clean on changed files)

## Files Created/Modified

- `src/checkmk_wizard/remote.py` — added `_server_with_receiver_port()` helper (with `import ipaddress`), wired into both register-command builders; added `sudo` to `register_agent_linux`'s and `install_agent_linux`'s manual-instruction strings.
- `src/checkmk_wizard/wizard.py` — added `_unusable_from_remote_target()` predicate; `_resolve_agent_registration_server`'s first early-out now calls it instead of `_looks_loopback`, and its warning text was generalized to not name `localhost` specifically; `_print_linux_manual`'s printed command now includes `sudo`.
- `tests/test_remote.py` — updated `test_windows_register_command_contains_flags` (pre-fix asserted an unported `--server` value); added 6 new tests for port-appending logic (plain hostname, explicit port passthrough, IPv4, bare IPv6, bracketed IPv6-with-port) and 2 new tests asserting `sudo` in `register_agent_linux`/`install_agent_linux` manual instructions.
- `tests/test_wizard.py` — added a parametrized `test_unusable_from_remote_target` covering loopback/bare-hostname/FQDN/IP cases; added 4 new `_resolve_agent_registration_server` tests (IP-literal passthrough, all-loopback early-out with a bare hostname, bare-hostname-triggers-prompt); added `test_print_linux_manual_includes_sudo`.

## Decisions Made

- Kept `_looks_loopback` unchanged (still exactly right for the per-target `h.ip` early-out, and covered by its own existing test) — the widened guard lives in a new sibling predicate, `_unusable_from_remote_target`, used only at the `checkmk_host` call site.
- Did not touch `windows_register_command`'s sudo handling — Windows has no `sudo` concept and its manual print was already correct.
- `AGENT_RECEIVER_PORT` remains a module constant, not user-configurable, per CLAUDE.md's simplicity-first constraint explicit in the plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pre-existing test asserted the unported `--server` value**
- **Found during:** Task 1
- **Issue:** `tests/test_remote.py::test_windows_register_command_contains_flags` asserted `"--server 'cmk.example'" in cmd` — this is exactly the pre-fix (buggy) behavior the plan's `<behavior>` block says must change ("quoting must wrap the FINAL value including the port"). Left unmodified it would fail after the fix.
- **Fix:** Updated the assertion to `f"--server 'cmk.example:{AGENT_RECEIVER_PORT}'" in cmd`, matching `_ps_quote`'s always-quote behavior.
- **Files modified:** `tests/test_remote.py`
- **Verification:** `uv run pytest tests/test_remote.py -x -q` — 30/30 passed.
- **Committed in:** `05cd5bf`

**2. [Rule 1 - Bug] My own initial test assertions over-assumed shlex.quote always adds quotes**
- **Found during:** Task 1
- **Issue:** First draft of `test_linux_register_command_appends_receiver_port_when_absent` and `test_linux_register_command_ipv4_gets_receiver_port` asserted a quoted `--server 'value'` form, but `shlex.quote()` only adds quotes when a value actually contains shell-special characters — `cmk.example:8000` and `192.168.97.129:8000` don't, so `shlex.quote` returns them bare.
- **Fix:** Corrected the two assertions to expect the unquoted form (`--server cmk.example:8000` / `--server 192.168.97.129:8000`); the bracketed-IPv6 assertions were left quoted since `[`/`]` do trigger `shlex.quote`'s quoting.
- **Files modified:** `tests/test_remote.py`
- **Verification:** `uv run pytest tests/test_remote.py -x -q` — 30/30 passed.
- **Committed in:** `05cd5bf`

**3. [Rule 3 - Blocking] Rich console line-wrapping broke a new sudo assertion**
- **Found during:** Task 2
- **Issue:** `test_print_linux_manual_includes_sudo` initially failed because `rich.console.Console`'s default 80-column width (used under `capsys`, a non-terminal capture) wrapped the long printed line, splitting `sudo cmk-agent-ctl register` across a line break so the plain substring assertion failed.
- **Fix:** Widened the module's shared `console` object's width to 200 for the duration of the test via `monkeypatch.setattr("checkmk_wizard.wizard.console.width", 200)` — test-only change, no production code touched.
- **Files modified:** `tests/test_wizard.py`
- **Verification:** `uv run pytest tests/test_wizard.py -x -q` — 202/202 passed.
- **Committed in:** `51ffec9`

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary changes; this plan only corrects the content of a `--server` CLI argument and printed instructional text.

## Self-Check: PASSED

- `src/checkmk_wizard/remote.py` — FOUND
- `src/checkmk_wizard/wizard.py` — FOUND
- `tests/test_remote.py` — FOUND
- `tests/test_wizard.py` — FOUND
- Commit `05cd5bf` — FOUND
- Commit `51ffec9` — FOUND
- Full suite: `uv run pytest -q` → 402 passed
- Lint: `uvx ruff check src tests` → 7 pre-existing findings (unrelated to changed files: `wizard.py:1450` B023, `test_site.py:45/67/89/175` SIM117, `test_wizard.py:253` RET501/PLR1711 — all confirmed present in a stashed pre-change baseline diff); zero new findings in `remote.py`, `wizard.py`'s changed regions, `test_remote.py`, or `test_wizard.py`'s changed regions.
