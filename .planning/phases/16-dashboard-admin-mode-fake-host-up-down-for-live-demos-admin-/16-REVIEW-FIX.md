---
phase: 16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-
fixed_at: 2026-10-02T00:00:00Z
review_path: .planning/phases/16-dashboard-admin-mode-fake-host-up-down-for-live-demos-admin-/16-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 4
skipped: 2
status: partial
---

# Phase 16: Code Review Fix Report

**Source review:** 16-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6
- Fixed: 4 (WR-05 was already fixed earlier)
- Skipped: 2

Work was done directly on `main` (explicit-path staging, unrelated uncommitted files left alone). `uv run pytest -q`: 809 passed.

## Fixed Issues

### WR-02: Ledger lost-update race
**Files modified:** `scripts/mqtt_poller.py`
**Commit:** 0fa6a09
**Applied fix:** new `AdminContext.prune_ledger()` prunes under the lock; a `publish_lock` serializes `should_publish` + `publish_admin_faked`. Concurrency fix, requires human verification.

### WR-03: `$`-anchored regexes accept trailing newline
**Files modified:** `scripts/mqtt_poller.py`
**Commit:** 0fa6a09
**Applied fix:** `_HOST_ID_RE`, `_ADMIN_COMMAND_ID_RE`, `_ADMIN_SAFE_ADDRESS_RE` now end in `\Z`.

### WR-04: One bad host aborts the whole batch
**Files modified:** `scripts/mqtt_poller.py`
**Commit:** 0fa6a09
**Applied fix:** `process_one` builds commands per action, catching `ValueError`; the host goes to `skipped`, the rest proceed (ack "no host could be commanded" if none). Only the actions actually built are sent and ledgered. Requires human verification.

### WR-05: publishAdminCommand throws from click handler
**Status:** already fixed (commit 97098bc). `AdminBar.tsx` now wraps `publishAdminCommand` in try/catch (line ~249). No change made. ADMIN_MAX_HOSTS left at 200 as instructed.

## Skipped Issues

### WR-01: `/admin-config.json` open
**File:** `deploy/dashboard-nginx.conf:73-84`
**Reason:** skipped by user decision (2026-10-02, `ADMIN_ALLOW_CIDR` declined; endpoint stays open for the closed demo network).

### WR-06: Keepalive re-injects results for hosts disabled for other reasons
**File:** `scripts/mqtt_poller.py:1391-1424, 1683-1736`
**Reason:** needs a design decision. The only safe fix is a poller-owned faked set persisted in the retained `admin/faked` payload (and restored on startup), which changes how the faked set is derived in Livestatus mode and affects the agreed restore/baseline behaviour. Not guessed; left for a decision.

---

_Fixer: Claude (bm-code-fixer)_
_Iteration: 1_
