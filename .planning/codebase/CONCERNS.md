# Codebase Concerns

**Analysis Date:** 2026-08-24

## Tech Debt

### No End-to-End Testing Against Live Environment

**Issue:** The wizard has not been tested against a live Checkmk site, real network targets, or actual SSH connections. Per README.md and CHECKMK_SETUP_CONFIGURATOR_PLAN.md, all tests are isolated (mocked REST API, localhost port scanning, no real SSH). This is a significant gap.

**Files:** `src/checkmk_wizard/wizard.py`, `src/checkmk_wizard/remote.py`, `src/checkmk_wizard/livestatus.py`

**Impact:** 
- Orchestration logic in `phase1_site_bringup()` through `phase7_activation()` is untested
- SSH automation paths may fail silently or produce unexpected output on real Linux/Windows targets
- Livestatus integration has no real-world validation
- Agent package installation and registration commands may not work as expected
- Firewall automation may not correctly handle all `ufw`/`firewall-cmd`/`nft` variants

**Fix approach:** 
1. Create integration test environment with a disposable Checkmk instance
2. Add end-to-end test suite that exercises all 7 phases against live environment
3. Add regression tests for known firewall/OS combinations
4. Document known working configurations and tested versions

### SSH Host Key Verification Disabled

**Issue:** In `src/checkmk_wizard/remote.py` line 105, `known_hosts=None` disables SSH host key verification entirely, making the wizard vulnerable to man-in-the-middle attacks.

**Files:** `src/checkmk_wizard/remote.py:105`

**Impact:** 
- An attacker on the network could intercept SSH connections and capture credentials or inject malicious agent packages
- No way to detect if connecting to an unexpected/compromised host

**Fix approach:** 
1. Change to `known_hosts="~/.ssh/known_hosts"` to use the user's existing known_hosts file
2. Add a `--trust-new-keys` flag to allow new keys on first connection only
3. Implement interactive key verification: prompt user to verify fingerprint on first connection
4. Document the security implications and configuration options clearly

### Secrets Passed as Command Arguments

**Issue:** Functions `linux_register_command()` (line 197-207) and `windows_register_command()` (line 210-217) in `src/checkmk_wizard/remote.py` pass passwords as shell command arguments. Even with `shlex.quote()`, these are visible in process listings and shell history.

**Files:** `src/checkmk_wizard/remote.py:197-217`

**Impact:** 
- Automation secrets exposed in `ps auxww`, shell history, audit logs
- Risk of credential leakage if logs are captured or system is compromised
- Violates credential handling best practices

**Fix approach:** 
1. For Linux: use `echo <secret> | cmk-agent-ctl register ... --password -` (if supported) to pass via stdin
2. For Windows: write secret to a temporary file with restricted permissions and use `--password-file`
3. Test with actual `cmk-agent-ctl` to confirm these alternatives work
4. Clear secrets from memory immediately after use

### Livestatus Socket Error Handling

**Issue:** `src/checkmk_wizard/livestatus.py:query_host_states()` (lines 18-57) connects to a UNIX socket without checking if the file exists, if permissions allow access, or if the socket is actually accessible. Connection failures raise bare `OSError` exceptions.

**Files:** `src/checkmk_wizard/livestatus.py:18-57`

**Impact:** 
- Phase 7 (`phase7_activation()` in wizard.py) may crash with cryptic error if:
  - Site was just activated and Livestatus hasn't started yet
  - Socket file is in wrong location or has wrong permissions
  - Site process crashed or was stopped
- No way to distinguish between "Livestatus not ready yet" vs. "permission denied" vs. "host truly down"
- User gets no actionable guidance on how to proceed

**Fix approach:** 
1. Add pre-flight checks: verify socket file exists and is readable before connecting
2. Wrap socket operations in specific exception classes (e.g. `LivestatusSocketNotFound`, `LivestatusPermissionDenied`)
3. Implement retry with exponential backoff for transient failures (e.g. Livestatus starting up)
4. Provide detailed error messages: "Livestatus socket not found at [path] — site may not have activated yet"
5. Add timeout to `socket.connect()` to avoid hanging indefinitely

### Network Scanner Could Hang on Large Ranges

**Issue:** `src/checkmk_wizard/scanner.py:scan_network()` (lines 63-85) has no timeout at the network/chunk level, only at the individual port level (DEFAULT_TIMEOUT = 1.5s). A /16 network chunked into /24s = 256 chunks × ~254 hosts per chunk = ~65k hosts. Even with semaphore capping concurrency to 256, this could take hours and provide no feedback beyond per-chunk progress.

**Files:** `src/checkmk_wizard/scanner.py:63-85`

**Impact:** 
- User runs scan on a /16 and the wizard hangs for extended periods with no way to estimate remaining time
- On slow networks, 1.5s port timeout × 3 ports × 65k hosts = many minutes
- No way to cancel mid-scan
- Phase 3 (`phase3_discovery()` in wizard.py) could block indefinitely

**Fix approach:** 
1. Add network-level timeout (e.g. 30 minutes max per chunk)
2. Implement per-chunk progress callbacks with time estimates
3. Add keyboard interrupt handling (Ctrl+C) to gracefully cancel
4. Warn user if CIDR is larger than /22 and recommend starting smaller
5. Cache results per chunk to allow resuming if interrupted

---

## Known Bugs

### Incomplete Error Recovery in Phase 5

**Update (2026-08-25), partial fix:** the most common trigger for this bug
was Phase 3 staging every scanned IP as a host under `host_name=ip`
(`wizard.py:184-186`), which collided with Phase 5's `create_host` call
whenever the user kept the default hostname (== IP) — silently dropping
`tag_agent`/`tag_snmp_ds`/`snmp_community`/`ipaddress` for the common path,
not just the naming-violation edge case described below. Phase 5 now goes
through `_create_or_update_host()` (`wizard.py:247-266`), which falls back
to `update_host_attributes()` on a collision instead of failing. See
`docs/PLAN-CONFORMANCE-AUDIT.md` Phase 5 section, 2026-08-25 entry, for
details and the remaining limitation (folder placement isn't corrected by
the fallback). The "continues anyway" bug described below is still
present for genuine create failures (e.g. an actually invalid hostname) —
only its most frequent trigger is closed.

**Issue:** In `phase5_onboarding()` (wizard.py, lines 177-258), if a host create/update fails, the wizard continues to attempt firewall and agent install anyway. This can lead to installing an agent on a host object that was never successfully created in Checkmk.

**Files:** `src/checkmk_wizard/wizard.py:177-258`

**Impact:** 
- Agent installed on target but host object missing/misconfigured in Checkmk
- User gets confusing state: host appears "up" but never shows in Checkmk monitoring
- No clear path to recover — requires manual cleanup and re-run

**Trigger:** 
1. Run phase 5
2. Enter hostname that violates Checkmk naming rules (e.g. contains invalid characters, duplicate hostname exists)
3. Host create fails with CheckmkAPIError
4. Wizard continues with firewall/SSH/agent install

**Fix approach:** 
1. Check `create_host()` response for success before proceeding to firewall/install steps
2. Add a "continue anyway?" prompt if host creation fails
3. Skip SSH automation steps for hosts that weren't successfully created
4. Return detailed error to user instead of silently proceeding

### Folder Assignment Race Condition

**Issue:** In `phase5_onboarding()` (wizard.py, line 201-205), hosts are created with a folder that may not exist if Phase 2 was skipped or if folder creation failed. The API will likely reject this, but the error handling is generic.

**Files:** `src/checkmk_wizard/wizard.py:201-205`

**Impact:** 
- Host creation fails with unclear error message if folder doesn't exist
- User has no way to know if it's a naming issue, permissions issue, or folder not found

**Fix approach:** 
1. Pre-flight check: verify all folders in `onboarded` list exist before Phase 5 starts
2. If a folder is missing, offer to create it or reassign to root
3. Return specific error message: "Folder '[folder]' does not exist"

---

## Security Considerations

### Automation Secret Storage and Prompt

**Risk:** Phase 1 (`phase1_site_bringup()`, lines 44-89) generates a random `cmkadmin` password and prints it to the console. If this is redirected to a log file or captured by a terminal multiplexer, it's visible in logs.

**Files:** `src/checkmk_wizard/wizard.py:44-89`

**Current mitigation:** 
- Console output only (not persisted by default)
- User is told "save this" and expected to copy/paste
- Random token generated with `secrets.token_urlsafe(16)` (cryptographically sound)

**Recommendations:** 
1. Accept `cmkadmin` password as input or environment variable instead of generating one
2. Avoid printing the password — require user to retrieve it from the site's automation.secret file manually
3. Add a note in README about disabling shell history for the session if credentials are sensitive

### Hardcoded Firewall Port and Protocol

**Risk:** Agent Receiver port (8000) is hardcoded in multiple places. If Checkmk is configured with a non-standard port, the wizard's firewall rules will be incorrect.

**Files:** 
- `src/checkmk_wizard/remote.py:23` (AGENT_RECEIVER_PORT = 8000)
- `src/checkmk_wizard/wizard.py:218-219` (used in probe)
- `src/checkmk_wizard/remote.py:129-164` (hardcoded in manual instructions)

**Current mitigation:** None — assumes port 8000 always

**Recommendations:** 
1. Query the site via REST API to determine the actual Agent Receiver port (`GET /version` or a site config endpoint)
2. Make port configurable via environment variable or config file
3. Store port in CheckmkConnection so all phases use the same value
4. Document assumption that port 8000 is used

### Package Integrity Not Verified

**Risk:** Agent packages downloaded in `phase5_onboarding()` (wizard.py, line 245) are not verified for integrity or authenticity. A compromised local network could inject malicious binaries.

**Files:** `src/checkmk_wizard/wizard.py:245`, `src/checkmk_wizard/api.py:143-150`

**Current mitigation:** HTTPS is used (assumed, via httpx default), but no checksum verification

**Recommendations:** 
1. Request SHA256 checksum from the REST API along with the package
2. Verify downloaded package matches checksum before installing
3. Allow user to manually verify fingerprints if desired

---

## Performance Bottlenecks

### Sequential Host Processing in Phase 5

**Issue:** `phase5_onboarding()` (wizard.py, lines 198-258) processes each host sequentially. For 100 hosts, even with fast SSH it could take 10+ minutes (1-2 min per host for firewall + OS check + agent download + install + register).

**Files:** `src/checkmk_wizard/wizard.py:177-258`

**Cause:** Each host waits for SSH connection, firewall check, OS compatibility check, package download, SCP transfer, install, and registration — all serial.

**Improvement path:** 
1. Download agent package once (shared across all Linux hosts of the same type)
2. Cache compatibility check results per OS type
3. Consider limited concurrency for SSH operations (e.g. 5 hosts in parallel) to balance throughput vs. resource usage
4. Separate REST API calls (which are fast) from SSH operations (which are slow)

### Network Scanner Inefficiency at Scale

**Issue:** `scan_network()` (scanner.py) doesn't report progress as it scans, only per-chunk (line 82-83). User gets one update per /24 chunk, which could be 1-2 minutes apart on slow networks.

**Files:** `src/checkmk_wizard/scanner.py:48-85`

**Improvement path:** 
1. Add per-host progress callback to show "scanning X.X.X.X..." in real-time
2. Estimate remaining time based on current scan rate
3. Allow user to set aggressive vs. conservative port timeout (trade speed for accuracy)

---

## Fragile Areas

### Firewall Detection and Manipulation

**Files:** `src/checkmk_wizard/remote.py:129-164`

**Why fragile:** 
- Relies on `command -v` to detect `ufw`, `firewall-cmd`, or `nft` — order matters (checks ufw first)
- Each firewall has different syntax and requires different permissions
- `sudo` is hardcoded — what if user can't sudo? What if `NOPASSWD` isn't configured?
- Detects by running commands; if host is sluggish, timeout could trigger unnecessarily
- No rollback if rule addition fails partway through

**Safe modification:** 
1. Before modifying firewall, always show the command that will be run and ask for confirmation
2. Implement `--dry-run` mode to show what would happen without executing
3. Add explicit `sudo -n` (non-interactive) check before attempting
4. Log all firewall commands and their exit codes for audit trail
5. Implement rollback: if install fails, remove the firewall rule that was added

### OS Compatibility Check

**Files:** `src/checkmk_wizard/remote.py:167-194`

**Why fragile:** 
- Compares target OS to the Checkmk host's OS exactly (line 184: `target.id == expected.id and target.version_id == expected.version_id`)
- This is too strict: Ubuntu 22.04 package may work on Ubuntu 22.10
- Silently returns `None` on any error, which means "compatibility unknown — proceed anyway"
- Parsing `/etc/os-release` is fragile if format is non-standard

**Safe modification:** 
1. Implement proper package compatibility matrix (e.g. "deb packages for Ubuntu ≥ 20.04", "rpm for RHEL ≥ 8")
2. Explicitly list tested combinations
3. Distinguish between "unknown" and "incompatible" — return `CompatibilityCheckError` if check itself fails
4. Test parsing against real `/etc/os-release` files from multiple distros

### Livestatus CSV Parsing

**Files:** `src/checkmk_wizard/livestatus.py:18-57`

**Why fragile:** 
- Manual CSV parsing without CSV module (lines 48-56)
- Uses `line.partition(";")` which only splits on first semicolon — what if hostname contains `;`?
- State parsing is lenient: `int(state)` catches `ValueError` and silently ignores malformed lines
- No handling if Livestatus returns an error response instead of data

**Safe modification:** 
1. Use Python's `csv` module instead of manual parsing
2. Validate that state is exactly 0, 1, or 2 — raise error on unexpected values
3. Check for Livestatus error responses (e.g. "500 Internal Error")
4. Document that hostnames containing semicolons are not supported

**Test coverage:** Currently not tested at all. Add unit tests for CSV parsing with edge cases (empty response, malformed lines, missing state columns).

### REST API Error Handling

**Files:** `src/checkmk_wizard/api.py:63-85`

**Why fragile:** 
- Generic `CheckmkAPIError` raised for all failures; no distinction between 400 (bad request), 401 (auth failed), 403 (forbidden), 404 (not found), 500 (server error)
- Caller can't decide whether to retry, skip, or fail
- No retry logic for transient 5xx errors

**Safe modification:** 
1. Create subclasses: `CheckmkAPIClientError` (4xx), `CheckmkAPIServerError` (5xx)
2. Implement automatic retry with exponential backoff for 5xx
3. Return different guidance based on error type:
   - 401: "Check authentication credentials"
   - 404: "Host/folder doesn't exist"
   - 400: "Invalid request — check input data"
   - 500+: "Checkmk server error — retry or contact administrator"

---

## Scaling Limits

### Network Scanner Concurrency

**Current capacity:** 
- Fixed concurrency: `DEFAULT_CONCURRENCY = 256` (line 19, scanner.py)
- Scales to ~65k hosts on a /16 network (256 chunks × 254 hosts per chunk)
- Per-chunk scan time: ~254 hosts × 3 ports × 1.5s timeout = 1140s = 19 min per chunk (worst case, no open ports)

**Limit:** At 256 concurrent connections, the wizard will hit kernel descriptor limits on hosts with low `ulimit -n` (default 1024). For a /16, 256 concurrent × 1.5s timeout = 384 potential concurrent connections if all hosts fail to answer quickly.

**Scaling path:** 
1. Make concurrency configurable (allow user to lower for constrained environments, raise for powerful ones)
2. Implement adaptive concurrency: start at 256, back off if hitting "too many open files" errors
3. Add `ulimit` check before scanning to warn user
4. Split very large CIDR blocks (>/16) into multiple sequential scans

### Host Onboarding Throughput

**Current capacity:** 
- Phase 5 processes hosts sequentially
- Per host: 1-2 min for SSH+firewall+OS check+agent install+register
- For 100 hosts: 100-200 minutes

**Limit:** No hard limit, but user experience degrades significantly over 50 hosts

**Scaling path:** 
1. Add parallel SSH handling (e.g. 5-10 concurrent SSH sessions)
2. Move REST API calls (fast) out of the serial path
3. Implement batching: REST host creates first (parallel), then SSH operations (limited parallel)
4. Add progress bar with ETA

### Activation Performance

**Current:** Phase 7 activates changes and queries Livestatus for all onboarded hosts. For very large deployments (1000+ hosts), this could time out.

**Scaling path:** 
1. Make health check optional for large deployments
2. Implement async Livestatus queries or return after first N hosts show up

---

## Dependencies at Risk

### asyncssh 2.24.0

**Risk:** asyncssh is not in the Checkmk ecosystem; it's a general-purpose library. Breaking changes or security vulnerabilities in this library could block the wizard.

**Impact:** 
- SSH automation (Phase 5.1/5.2) stops working if asyncssh version is incompatible
- Need to audit for security advisories

**Migration plan:** 
1. Monitor asyncssh releases for security updates
2. Have a plan to use paramiko or built-in `ssh` subprocess calls as fallback
3. Document minimum supported asyncssh version

### httpx 0.28.1

**Risk:** HTTP client library not specific to Checkmk. Could have TLS/certificate validation issues.

**Impact:** 
- REST API calls fail if httpx has a bug
- Certificate validation might not work correctly in all environments

**Migration plan:** 
- Consider pinning to known-good version
- Monitor for security updates
- Test against various Python/OpenSSL combinations

---

## Missing Critical Features

### No Resume/Checkpoint Support

**Issue:** If the wizard crashes or is interrupted mid-execution, there's no way to resume from where it left off. User must start from Phase 1 again.

**Impact:** 
- Re-running creates duplicate host objects, folders
- Idempotency is not guaranteed (Phase 2 folder creation may fail if folder already exists)
- User must manually track which phases completed

**Blocking:** Not critical for initial MVP, but becomes important with larger deployments

**Fix approach:** 
1. Write phase completion checkpoints to a local state file after each phase
2. On startup, offer to resume from last checkpoint
3. Make all operations idempotent (e.g. update host instead of create if it already exists)

### No Dry-Run Mode

**Issue:** Wizard makes live changes to Checkmk without a way to preview what will happen.

**Impact:** 
- User can't see plan before executing
- Risky for production environments

**Fix approach:** 
1. Add `--dry-run` flag to all phases
2. Show what would be created/modified without actually making changes
3. Allow user to review plan and confirm before proceeding

### No Configuration File Support

**Issue:** All input is interactive. For repeated setups or automation, this is tedious.

**Impact:** 
- Can't script the wizard
- Must manually enter subnet, hosts, credentials every time

**Fix approach:** 
1. Support YAML/JSON config file with all phase inputs
2. Fall back to prompts if config file missing
3. Document config file schema

---

## Test Coverage Gaps

### Wizard Orchestration Logic (Phases 1-7)

**What's not tested:** 
- The entire `run()` and `main()` functions (wizard.py:318-331)
- All 7 phase functions' interaction and state management
- Error handling across phases (e.g. Phase 1 fails → how do Phases 2-7 behave?)
- User prompt handling and validation

**Files:** `src/checkmk_wizard/wizard.py:318-331`

**Risk:** 
- Phases may call each other with invalid state
- Global questionary prompts may not behave as expected in test/CI environments
- Resource cleanup (e.g. CheckmkClient context manager) may leak on error

**Coverage:** 0% (not tested at all)

### Livestatus Integration

**What's not tested:** 
- `query_host_states()` function
- CSV parsing logic
- Socket errors and retry behavior
- Empty results, malformed responses

**Files:** `src/checkmk_wizard/livestatus.py`

**Risk:** 
- Phase 7 health check silently fails or crashes
- User gets no feedback on host states

**Coverage:** 0% (not tested at all)

### SSH Remote Operations

**What's not tested:** 
- Real SSH connections (mocked, only function signatures tested)
- Firewall detection and rule application
- Agent installation and registration
- OS compatibility checks

**Files:** `src/checkmk_wizard/remote.py`

**Risk:** 
- All firewall and SSH automation fails silently or with cryptic errors on real hosts
- No real-world data on which firewall backends and Linux distros work

**Coverage:** ~30% (only command generation and parsing tested; not actual SSH operations)

### Checkmk API Client

**What's not tested:** 
- Real HTTP calls (mocked via respx)
- Edge cases: 404 responses, 500 errors, slow servers, network timeouts
- Retry behavior on transient failures
- Large response bodies (e.g. downloading multi-MB agent packages)

**Files:** `src/checkmk_wizard/api.py`

**Risk:** 
- Untested 5xx retry logic may fail in production
- Large package downloads may crash or time out

**Coverage:** ~70% (happy path covered, error cases minimal)

### Network Scanner

**What's not tested:** 
- Real network scanning
- Large /16 networks (only tested on localhost)
- Actual firewall/filtering behavior
- Timeout and hang recovery

**Files:** `src/checkmk_wizard/scanner.py`

**Risk:** 
- Hangs on real networks if something goes wrong
- Progress reporting doesn't work as expected

**Coverage:** ~50% (basic logic tested on localhost, not at scale)

**Priority:** Add integration tests for the wizard's orchestration and livestatus, prioritize SSH/firewall real-world testing.

---

*Concerns audit: 2026-08-24*
