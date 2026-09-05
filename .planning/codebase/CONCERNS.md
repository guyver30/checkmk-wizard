# Codebase Concerns

**Analysis Date:** 2026-09-05

## Tech Debt

**No resume/checkpoint support across the 7-phase run:**
- Issue: `run()` in `src/checkmk_wizard/wizard.py:1766-1776` chains phases 1-7 in a single process with no persisted state between phases. An uncaught exception, terminal disconnect, or `Ctrl-C` at any point loses all progress from earlier phases (scanned hosts, classification choices, onboarding results already applied server-side aren't re-discoverable by the wizard itself).
- Files: `src/checkmk_wizard/wizard.py` (`run`, `main`)
- Impact: A crash deep into Phase 5 (e.g. on host 40 of 50) forces a full re-run from Phase 1; the operator must remember/re-enter every prior answer. Documented as a known limitation in `docs/PLAN-CONFORMANCE-AUDIT.md` (line ~644) but never addressed.
- Fix approach: Serialize `WizardState`/`OnboardedHost` list to disk after each phase and offer a "resume from last checkpoint" path on startup.

**Sequential (non-concurrent) per-host onboarding:**
- Issue: `_onboard_hosts()` (`src/checkmk_wizard/wizard.py:1333-1538`) processes each host in a plain `for h in hosts:` loop — SSH connect, firewall fix, agent download/install, SMART install, and service discovery all run one host at a time even though every step is already `async`.
- Files: `src/checkmk_wizard/wizard.py:1333`
- Impact: Onboarding N Linux hosts takes roughly N times as long as one host (SSH round-trips, package uploads, and `sleep()`-based discovery retries in Phase 6 all serialize). Flagged as a known limitation in `docs/PLAN-CONFORMANCE-AUDIT.md` ("sequential (non-concurrent) per-host processing").
- Fix approach: Run the per-host body under a bounded `asyncio.Semaphore` + `asyncio.gather`, mirroring the concurrency pattern already used in `scanner.py`.

**Config snapshot files accumulate uncleaned in the working directory:**
- Issue: Phase 7 (`phase7_activation`, `src/checkmk_wizard/wizard.py:1751-1760`) writes `config_snapshot_<timestamp>.json` to the current working directory on every run, with no cleanup, rotation, or output-directory option.
- Files: `src/checkmk_wizard/wizard.py:1758`; observed artifacts: `config_snapshot_20260826_163912.json`, `config_snapshot_20260826_164913.json`, `config_snapshot_20260826_165819.json` at repo root, plus six more under `src/config_snapshot_*.json` (all gitignored via `config_snapshot_*.json` in `.gitignore`, but not deleted from disk).
- Impact: Disk clutter grows unbounded across repeated test runs; the three root-level snapshot files are owned by `root:root` (a prior run was executed with elevated privileges), which the current non-root user cannot delete without `sudo`. This is also why `uv run pytest` prints a `PytestCacheWarning: ... Permission denied: .pytest_cache/v/cache/nodeids` — `.pytest_cache/` itself has root-owned entries from the same prior privileged run.
- Fix approach: Accept an `--output-dir` (or default to a dedicated `snapshots/` folder), and document/avoid running the wizard or its test suite as root.

**Fragile manual AST/regex parsing of Checkmk's on-disk config:**
- Issue: `site.list_agent_registered_hosts()` → `_parse_host_attributes()` (`src/checkmk_wizard/site.py:181-225`) reverse-engineers WATO's `hosts.mk` files by walking a Python AST looking for one specific `host_attributes.update({...})` call shape. This already broke once (a prior regex-based version silently returned `{}` for every real file — see the docstring's "Bug fixed 2026-08-27" note) and returns `{}` silently on any parse failure, print no warning.
- Files: `src/checkmk_wizard/site.py:181-225`, called from `wizard.py:335` (delete-site warning flow)
- Impact: A future Checkmk release that changes how `hosts.mk` is generated (e.g. a different call shape or an additional wrapping construct) will silently make agent-registration warnings disappear again — the delete-site flow would stop warning about stale agent registrations with no visible error, reproducing the exact 2026-08-27 bug in a new form.
- Fix approach: Add a self-check (e.g. warn if zero hosts are found across a site known to have `hosts.mk` files) or prefer the REST API (`list_hosts()`, already in `api.py`) over local file parsing wherever a live site connection is available.

**Manual/fragile Livestatus CSV parsing:**
- Issue: `livestatus.query_host_states()` (`src/checkmk_wizard/livestatus.py:44-56`) parses the raw LQL CSV response by splitting each line on the first `;` only and silently `continue`-ing past any line that doesn't parse as an int state — no column-count validation, no handling of embedded semicolons.
- Files: `src/checkmk_wizard/livestatus.py:47-55`
- Impact: A malformed or unexpected response silently drops hosts from the returned state map rather than surfacing an error; Phase 7's post-activation table (`wizard.py:1726-1735`) would then show `"unknown"` for a host with no visible cause. Explicitly flagged as still-present in `docs/PLAN-CONFORMANCE-AUDIT.md` ("Already known ... confirmed still present").
- Fix approach: Request `OutputFormat: json` instead of `csv` (Livestatus supports it) and parse with `json.loads`, eliminating the manual split logic entirely.

**No pre-flight check that Livestatus is reachable before Phase 7 queries it:**
- Issue: `phase7_activation()` calls `livestatus.query_host_states()` unconditionally once `hosts` is non-empty (`wizard.py:1726-1735`); `query_host_states()` itself does not catch `OSError`/`socket.timeout` from `socket.create_connection()`.
- Files: `src/checkmk_wizard/livestatus.py:34`, `src/checkmk_wizard/wizard.py:1726`
- Impact: If Livestatus-over-TCP was never actually enabled (e.g. the container-mode path in Phase 1 warned about this but the operator proceeded anyway — `wizard.py:374-380`), Phase 7 raises an uncaught `OSError`/`ConnectionRefusedError` and crashes the wizard on its very last phase, after all onboarding work is already done.
- Fix approach: Wrap the `query_host_states()` call in `phase7_activation()` with a `try/except OSError` and print a yellow warning instead of crashing, consistent with every other phase's degrade-gracefully pattern.

**No `[tool.ruff]` / lint configuration despite `.ruff_cache/` present:**
- Issue: `pyproject.toml` has no `[tool.ruff]` section; ruff (evidenced by `.ruff_cache/`) is apparently run with all defaults, no project-specific rule selection, line length, or per-file ignores.
- Files: `pyproject.toml` (no `[tool.ruff]` block)
- Impact: Lint behavior is whatever ruff's shifting defaults happen to be on whichever version is installed locally, with no reproducibility across contributors/CI. One inline `# noqa: DTZ005` in `wizard.py:1758` implies at least the `DTZ` rule set is active by default, but the project doesn't pin or declare it.
- Fix approach: Add an explicit `[tool.ruff]` (and `[tool.ruff.lint]`) section pinning the rule selection currently relied upon.

## Known Bugs

**`_create_or_update_host()` cannot move a host between folders on fallback:**
- Symptoms: When Phase 5 promotes a scanned IP into a named host inside a non-root Phase-2 folder, and Phase 3's IP-named placeholder already exists (e.g. Phase 2 was skipped or the folder assignment logic didn't stage it there), the fallback path in `_create_or_update_host()` (`src/checkmk_wizard/wizard.py:804-828`) only calls `update_host_attributes()` — Checkmk's host-config `PUT` does not support changing a host's folder. The host silently stays in whatever folder it was originally created in.
- Files: `src/checkmk_wizard/wizard.py:804-828`
- Trigger: A Phase-3-staged placeholder host ends up in a different folder than where Phase 5 tries to place its promoted counterpart, and the create collides.
- Workaround: Documented directly in the function's docstring and in `docs/WIZARD-OPERATION.md`; in the current common path (Phase 3 now stages hosts directly into their eventual Phase 2 folder) this rarely triggers, but it is not eliminated for every code path — e.g. a host that changes folder assignment between scan and promotion.

**`bootstrap_agent_registration_secret()` is not live-verified:**
- Symptoms: Unknown/unconfirmed — the function's own docstring (`src/checkmk_wizard/api.py:493-499`) states its `auth_option` reset-via-PUT request shape was inferred from two other, separately-verified endpoints, not tested end-to-end against a running Checkmk site.
- Files: `src/checkmk_wizard/api.py:464-546`
- Trigger: Container-mode Phase 1 bring-up (`wizard.py:444-461`) when no local `agent_registration` secret file is readable and a `cmkadmin_password` was supplied.
- Workaround: On failure, the wizard catches `CheckmkAPIError` and falls back to reusing the general `automation` credential for registration (`wizard.py:456-461`) — a silent-but-safe degrade, not a crash, but the "dedicated least-privilege registration user" feature may simply never activate in container mode without anyone noticing.

**SNMP `snmp_community` attribute payload shape is unverified:**
- Symptoms: Unknown/unconfirmed — the SNMP host-creation path (`wizard.py:1349-1373`) sends `"snmp_community": {"type": "v1_v2_community", "community": ...}` with an inline comment explicitly noting "the exact snmp_community attribute schema below was not confirmed against live Checkmk REST API docs."
- Files: `src/checkmk_wizard/wizard.py:1354-1369`
- Trigger: Onboarding any host classified as `os_family == "snmp"` in Phase 4.
- Workaround: None built in; `CheckmkAPIError` from a rejected payload is caught and printed as a yellow warning (`wizard.py:1371-1372`), so the host may end up created without a working SNMP community — verify against the target site's own OpenAPI spec before relying on this in production, per the code comment.

## Security Considerations

**Plaintext HTTP is the default transport for all REST and GUI-login traffic:**
- Risk: `CheckmkConnection.proto` defaults to `"http"` (`src/checkmk_wizard/api.py:36`), and every bootstrap/password-change helper (`bootstrap_automation_user`, `bootstrap_agent_registration_secret`, `change_cmkadmin_password` in `api.py`) also defaults `proto="http"`. The REST client's `Authorization: Bearer <user> <secret>` header (`api.py:64`) and the GUI login's `_username`/`_password` form POST (`api.py:301-311`) are therefore sent in cleartext by default over the network to `checkmk_host`.
- Files: `src/checkmk_wizard/api.py:36`, `:64`, `:301-311`, `:359`, `:506`, `:582`
- Current mitigation: None — the wizard never prompts for or defaults to `https`, and there's no TLS-verification-skip warning either way since HTTP is simply assumed.
- Recommendations: Default to `https` (with an explicit opt-out for lab/loopback use), or at minimum warn the operator when `checkmk_host` resolves to something other than `localhost`/loopback and `proto` is still `http`.

**Registration/sudo secrets appear in remote process argv, visible via `ps`:**
- Risk: `linux_register_command()`/`windows_register_command()` (`src/checkmk_wizard/remote.py:342-371`) embed the plaintext automation/registration secret directly in a `cmk-agent-ctl register --password <secret>` command string. This string is executed on the target host via `_run_sudo()` (`remote.py:190-206`), which runs `sudo -S -p '' <cmd>` as a single shell command — for the duration of that command's execution, any local user on the target with process-list access (`ps aux`, `/proc/<pid>/cmdline`) can read the plaintext secret.
- Files: `src/checkmk_wizard/remote.py:342-371` (command construction), `remote.py:421-438`, `remote.py:441-494` (execution sites), `wizard.py:1413-1416`, `1453-1456`, `1569-1574` (also printed to the console/terminal scrollback in manual-instructions paths)
- Current mitigation: None. The sudo *password itself* is fed via stdin (`_run_sudo`'s `input=` parameter) and does not appear in argv — only the registration secret is exposed this way.
- Recommendations: Use `cmk-agent-ctl register`'s support for reading the password from stdin (if available) or a temporary credential file with restrictive permissions, removed immediately after use, instead of passing it as a CLI argument.

**SSH host-key verification is disabled for every managed host:**
- Risk: `_connect()` (`src/checkmk_wizard/remote.py:172-178`) passes `known_hosts=None` to `asyncssh.connect()` unconditionally, disabling host-key verification for every SSH session the wizard opens (firewall fixes, agent install, SMART setup, service discovery scans).
- Files: `src/checkmk_wizard/remote.py:173`
- Current mitigation: None — no `known_hosts` file, no TOFU (trust-on-first-use) prompt, no warning printed to the operator.
- Recommendations: At minimum, print a one-time warning when connecting to a host for the first time; ideally support an optional `known_hosts` path and only fall back to `None` when the operator explicitly opts in (e.g. for lab environments).

**Generated passwords and secrets are printed to the terminal in plaintext:**
- Risk: The freshly generated `cmkadmin` password (`secrets.token_urlsafe(16)`, `wizard.py:215`) and every automation/registration secret path print the actual credential value to the console (`wizard.py:220`, and every `linux_register_command`/`windows_register_command` printed in the manual-instructions fallback paths, e.g. `wizard.py:1416`, `:1574`).
- Files: `src/checkmk_wizard/wizard.py:215-220`, `:1413-1416`, `:1453-1456`, `:1569-1574`
- Current mitigation: None — no `--quiet`/redaction option; relies entirely on the operator's terminal not being logged, screen-shared, or recorded (note: `screen1.png` and `PROMPT_LOG.md` exist in this working tree, illustrating the kind of artifact that can inadvertently capture such output).
- Recommendations: Offer a redacted/masked display mode, or write one-time secrets to a short-lived local file the operator must explicitly open, rather than echoing to stdout.

**`.planning/.pending-auth-captures.jsonl` present and untracked in the working tree:**
- Risk: An untracked file named `.pending-auth-captures.jsonl` exists under `.planning/` (outside this project's own `src/checkmk_wizard` code — likely produced by tooling around this repository rather than the wizard itself). Its name strongly suggests captured authentication material.
- Files: `.planning/.pending-auth-captures.jsonl` (existence noted only; contents were not read per this audit's data-handling rules)
- Current mitigation: Not covered by `.gitignore` — currently shows as untracked (`??`) in `git status`, meaning it would be swept into a `git add -A`/`git add .` if one were ever run.
- Recommendations: Confirm what writes this file and whether it belongs in `.gitignore`; if it can contain real credentials, ensure it is never committed and is deleted/rotated after use.

## Performance Bottlenecks

**Phase 3 network scan concurrency is a single fixed global semaphore per scan:**
- Problem: `scan_network()` (`src/checkmk_wizard/scanner.py:63-85`) uses one `asyncio.Semaphore(concurrency)` (default 256) shared across every host×port probe in a /24 chunk, with `timeout=1.5s` per probe (`DEFAULT_TIMEOUT`). For a filtered/firewalled subnet, most probes take the full timeout before failing, and the concurrency ceiling means a full /24 × 3-ports scan can still take on the order of `(254*3/256) * 1.5s ≈ 4.5s` per chunk in the worst case, scaling further for larger CIDRs (multiple /24 chunks processed sequentially — `for chunk in chunk_network(network):` in `scan_network()`, `scanner.py:75`).
- Files: `src/checkmk_wizard/scanner.py:63-85`
- Cause: Chunks are processed one at a time rather than concurrently; only within a chunk is there any parallelism.
- Improvement path: Run chunks concurrently too (bounded by the same or a second semaphore), rather than sequential `for chunk in chunk_network(network)`.

**Phase 6 discovery retries add up to ~60s of blocking `asyncio.sleep` per host with unresolved services:**
- Problem: `phase6_discovery()` (`src/checkmk_wizard/wizard.py:1612-1648`) retries `start_service_discovery(mode="fix_all")` after fixed delays `_DISCOVERY_RETRY_DELAYS_SECONDS = (10, 20, 30)` (`wizard.py:1590`) whenever any Phase-5-requested service hasn't shown up yet — per host, sequentially (see "Sequential ... onboarding" tech-debt item above).
- Files: `src/checkmk_wizard/wizard.py:1590`, `:1632-1644`
- Cause: Combined with the sequential per-host loop, a batch of 10 Linux hosts that are all slow to report services could add up to ~10 minutes of pure wait time to a single wizard run.
- Improvement path: Run the retry loop across hosts concurrently (each host's own delay independent of the others), consistent with the sequential-onboarding fix noted above.

## Fragile Areas

**`_expected_open_ports_by_hostname()` / `_ping_only_hostnames()` depend on precise IP/hostname bookkeeping across phases:**
- Files: `src/checkmk_wizard/wizard.py:830-916`
- Why fragile: These two functions reconstruct "which scanned host is this now called" by cross-referencing `ScannedHost.ip` against `OnboardedHost.ip` in two separately-maintained lists (`scan_results`, `onboarded`) built across three different phases (3, 4, 5). Any future change that lets a host's IP change between scan and promotion, or that introduces duplicate IPs across folders, would silently misattribute expected-open-port or ping-only rules to the wrong host.
- Safe modification: Any change to `ScannedHost`/`OnboardedHost` field semantics (especially `ip`) must be accompanied by updates to both functions and their existing tests in `tests/test_wizard.py` (`test_expected_open_ports_by_hostname_skips_hosts_with_no_ports` and neighbors).
- Test coverage: Covered by unit tests, but only for single-folder, non-duplicate-IP scenarios — no test exercises duplicate IPs across two different Phase-2 folders.

**`_gui_login()` CSRF/session-cookie flow is coupled to Checkmk's HTML login page structure:**
- Files: `src/checkmk_wizard/api.py:286-313`
- Why fragile: `bootstrap_automation_user()`, `bootstrap_agent_registration_secret()`, and `change_cmkadmin_password()` all depend on scraping a `global_csrf_token = "..."` JavaScript assignment out of the raw login page HTML via a single regex (`_CSRF_TOKEN_RE`, `api.py:286`). A Checkmk UI update that changes this variable name, quoting style, or moves CSRF handling to a meta tag/cookie would break all three bootstrap functions at once with a generic "no CSRF token found" error, not a Checkmk-version-specific one.
- Safe modification: Any Checkmk version bump used for testing should include manually re-verifying this regex still matches; consider capturing the exact Checkmk version this was verified against (already partially done — code comments cite "2.4.0p35 CE" throughout) and asserting/warning on version drift.
- Test coverage: Exercised via mocked HTTP responses (`respx`) in `tests/test_api.py`, which by construction always match the assumed HTML shape — provides no protection against upstream Checkmk changing that shape.

## Scaling Limits

**Full-batch shared SSH/sudo credentials assume homogeneous Linux fleet:**
- Current capacity: `_establish_ssh_access()` (`wizard.py:1231-1296`) collects one SSH username/password-or-key and, if needed, one sudo password for the *entire* batch of Linux hosts, tested against only the first host (`linux_hosts[0].ip`).
- Limit: A batch where even one Linux host has different SSH credentials falls back to manual instructions for *that host only* (each remote.py function's own `check_ssh_reachable()` guard) — acceptable for small/homogeneous fleets but doesn't scale to environments with per-host credential rotation or varied service accounts.
- Scaling path: Support per-host (or per-group) credential sets, prompted once per distinct credential set rather than once globally.

**Phase 3 scanning holds full result sets in memory and issues one `create_host` call per discovered IP sequentially:**
- Current capacity: `phase3_discovery()` (`wizard.py:633-704`) calls `client.create_host()` once per scanned+alive IP, in a plain `for r in results:` loop, immediately after each subnet's scan completes.
- Limit: A large subnet (e.g. a /16 chunked into 256 /24s) with many responsive hosts would issue hundreds of sequential REST calls with no batching/concurrency, extending wizard runtime roughly linearly with host count.
- Scaling path: Batch host creation with bounded concurrency, same as the scanning improvement noted under Performance Bottlenecks.

## Dependencies at Risk

**`asyncssh`, `httpx`, `questionary`, `rich` are unpinned above a minimum version (`>=`):**
- Risk: `pyproject.toml` declares all four core dependencies with `>=` lower bounds only (`asyncssh>=2.24.0`, `httpx>=0.28.1`, `questionary>=2.1.1`, `rich>=15.0.0`), no upper bounds. `uv.lock` pins exact resolved versions for reproducible installs, but a `uv sync --upgrade` (or a fresh lock) could pull in a breaking major version of any of these with no warning from the manifest itself.
- Impact: A breaking `asyncssh` or `httpx` release could silently change connection/auth semantics (e.g. `known_hosts` handling, timeout behavior) used throughout `remote.py`/`api.py`.
- Migration plan: Add upper-bound or exact pins for at least `asyncssh` and `httpx` given how deeply their specific API surface (`asyncssh.connect(known_hosts=...)`, `httpx.AsyncClient` header/timeout semantics) is relied upon.

## Missing Critical Features

**No full site backup — only hosts + folders, no rules/users:**
- Problem: Phase 7's `config_snapshot_*.json` (`wizard.py:1737-1760`) only captures `list_hosts()` and `list_folders()`. Every rule created by the wizard itself (TCP-port checks, PING checks, threshold rules, service-discovery rules — all in `wizard.py`'s `_create_*_rules` helpers) plus any pre-existing site-wide rules, users, and roles are absent from the snapshot.
- Blocks: Using the snapshot as a genuine disaster-recovery artifact, as originally scoped in `docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md` ("known good baseline ... for diffing/disaster recovery") — explicitly documented in `docs/PLAN-CONFORMANCE-AUDIT.md` as a "scope correction, not full closure."

**Disabled-services baseline ruleset never implemented:**
- Problem: The original plan's Phase 6 baseline-ruleset scope included suppressing known-noisy disabled-services checks; this remains deliberately deferred (`docs/PLAN-CONFORMANCE-AUDIT.md`, "Disabled-services baseline ruleset — still deliberately deferred") since there is no "ask the operator to pick from what's there" mitigation analogous to the systemd/Windows service-selection flow.
- Blocks: Fully automated noise-free monitoring baselines without a manual post-onboarding cleanup pass in the Checkmk UI.

## Test Coverage Gaps

**No test exercises duplicate IPs across multiple Phase 2 folders:**
- What's not tested: `_expected_open_ports_by_hostname()`/`_ping_only_hostnames()` (`wizard.py:830-916`) behavior when the same IP is somehow scanned into two different folders in one run.
- Files: `tests/test_wizard.py` (no matching test found via `grep -n "def test_"` search for this scenario)
- Risk: Silent misattribution of TCP-port/PING rules to the wrong host if this edge case is ever hit in practice.
- Priority: Low (requires an unusual dual-folder-scan-of-same-subnet setup to trigger).

**No integration/live-site test for `bootstrap_agent_registration_secret()`:**
- What's not tested: End-to-end behavior against a real Checkmk site — only mocked HTTP responses via `respx` in `tests/test_api.py` (`test_bootstrap_agent_registration_secret_success` and neighbors), which the function's own docstring already flags as unverified against a live site.
- Files: `tests/test_api.py:399-461`, `src/checkmk_wizard/api.py:464-546`
- Risk: The mocked tests can pass while the real Checkmk endpoint rejects the actual request shape — this exact class of failure has already occurred once for the sibling systemd-discovery ruleset (per `docs/PLAN-CONFORMANCE-AUDIT.md`'s account of needing live-site debugging to get that payload shape right).
- Priority: Medium — affects a real, reachable code path (container-mode Phase 1 bring-up), not a hypothetical one.

**No test for concurrent/large-batch scanning or onboarding performance characteristics:**
- What's not tested: Runtime/behavior of `scan_network()` or `_onboard_hosts()` under realistic host counts (tens to hundreds) — existing tests use small, fixed host lists.
- Files: `tests/test_scanner.py`, `tests/test_wizard.py`
- Risk: The sequential-processing performance issues noted above have no regression test that would catch a further slowdown or catch a future concurrency fix's correctness.
- Priority: Low — these are known, already-documented performance characteristics, not silent bugs.

---

*Concerns audit: 2026-09-05*
