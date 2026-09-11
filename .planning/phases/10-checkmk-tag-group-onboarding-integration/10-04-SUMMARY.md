---
phase: 10-checkmk-tag-group-onboarding-integration
plan: 04
subsystem: onboarding
tags: [questionary, checkmk-rest-api, host-tags, dataclass]

# Dependency graph
requires:
  - phase: 10-checkmk-tag-group-onboarding-integration (plan 02)
    provides: DEVICE_TYPE_TAG_GROUP_ID, _load_device_types(), _ensure_device_type_tag_group() and device_types.json
provides:
  - OnboardedHost.device_type/.alias fields
  - Phase 4 device-type select and optional alias text prompt, config-driven
  - tag_device_type and alias merged into all three Phase 5 host-creation attribute dicts (snmp, ping, agent)
affects: [phase-10-05-poller-integration, phase-11-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared attribute-fragment helper (_device_type_and_alias_attributes) merged into each call site's dict via **-unpack, instead of copy-pasting the same two keys three times"

key-files:
  created: []
  modified:
    - src/checkmk_wizard/wizard.py
    - tests/test_wizard.py

key-decisions:
  - "D-07/D-09 confirmed: device_type and alias prompts live in Phase 4 (Classification), applied in Phase 5 as tag_device_type (tag) and alias (native Checkmk attribute, no tag_ prefix)"
  - "alias is omitted from the attributes dict entirely when unset, never sent as an empty string, so a wizard re-run never clears an operator-set alias in the Checkmk UI (T-10-17)"

patterns-established:
  - "Config-driven questionary.select choices (built from _load_device_types() at prompt time) rather than a hardcoded choice list, so a per-site taxonomy needs no code change"

requirements-completed: [TAG-02]

# Metrics
duration: ~20min
completed: 2026-09-11
---

# Phase 10 Plan 04: Device Type and Alias Onboarding Prompts Summary

**Phase 4 now prompts for a config-driven device type and optional display alias per host, and Phase 5 applies both as real Checkmk host attributes (tag_device_type + alias) across all three monitoring-method branches.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-09-11
- **Tasks:** 3 (Task 3 required no additional file changes — see Deviations)
- **Files modified:** 2 (`src/checkmk_wizard/wizard.py`, `tests/test_wizard.py`)

## Accomplishments

- `OnboardedHost` gained `device_type: str = "other"` and `alias: str | None = None`, both defaulted and appended last so existing keyword-argument call sites keep working unchanged.
- `phase4_classification` now asks a `questionary.select` device-type prompt whose choices come from `_load_device_types()` (device_types.json), and a `questionary.text` alias prompt where a blank/whitespace answer becomes `None` and a non-blank answer is stored stripped.
- `_onboard_hosts`'s three attribute-building branches (snmp, ping, agent) all merge a new shared helper's output — `_device_type_and_alias_attributes(h)` — which derives the attribute key as `f"tag_{DEVICE_TYPE_TAG_GROUP_ID}"` (never a hardcoded `"tag_device_type"` literal) and omits the `alias` key entirely when unset.
- Phase 2 folder-default and Phase 3 IP-placeholder host attribute assertions are untouched — those hosts still carry no device type, relying on Checkmk's own tag-group default.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add device_type and alias to OnboardedHost and prompt for them in Phase 4** - `2d38e3a` (feat)
2. **Task 2: Apply tag_device_type and alias at all three Phase 5 host-creation call sites** - `27cda52` (feat)
3. **Task 3: Repair every pre-existing test whose answer iterator the new prompts shortened** - no separate commit; folded into Task 1's commit (see Deviations below)

## Files Created/Modified

- `src/checkmk_wizard/wizard.py` - `OnboardedHost.device_type`/`.alias` fields; two new Phase 4 prompts; `_device_type_and_alias_attributes()` helper; all three `_onboard_hosts` attribute dicts extended
- `tests/test_wizard.py` - 4 pre-existing `phase4_classification`-driving tests repaired with two new answers each; 8 new tests covering device-type choice-list fidelity, blank/stripped alias, per-monitoring-method `tag_device_type`, and alias absent-vs-present at the Phase 5 attribute level

## Decisions Made

- Followed D-07/D-09 exactly as locked in CONTEXT.md: prompt placement in Phase 4, attribute application in Phase 5, `alias` as a native Checkmk attribute (no `tag_` prefix).
- Used `**_device_type_and_alias_attributes(h)` unpacking into each branch's existing dict literal rather than building the dict imperatively, to keep each branch's method-specific keys visually intact and the diff minimal (Rule: Surgical Changes).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Folded Task 3's iterator repairs into Task 1's commit**
- **Found during:** Task 1
- **Issue:** Task 1's own `<verify>` line is `uv run pytest tests/test_wizard.py -q && uv run ruff check src/ tests/`. The moment the two new Phase 4 prompts landed, the four pre-existing fixed-length `answers = iter([...])` tests (`test_phase4_offers_ping_monitoring_method`, `test_phase4_prompts_expected_open_ports_default_from_scan`, `test_phase4_expected_open_ports_blank_skips`, `test_phase4_rejects_out_of_range_port`) raised `StopIteration`, so Task 1's own verify command could not pass without also doing the work the plan assigned to Task 3.
- **Fix:** Appended the two new answers (device type, then alias) in prompt order to all four iterators as part of Task 1's commit, with a comment above each iterator naming what each element answers, per the plan's own request for that comment style.
- **Files modified:** `tests/test_wizard.py` (same file Task 3 would have touched)
- **Verification:** `uv run pytest tests/test_wizard.py -q` — 158 passed after Task 1's commit; `uv run pytest -q` — 345 passed after Task 2's commit (full suite, up from a 337-test baseline)
- **Committed in:** `2d38e3a` (Task 1 commit)

Task 3's own read_first/action pointed at exactly these same four tests and this same fix, so no further file change was needed under Task 3's name — its acceptance criteria (full suite green, `grep -c 'phase4_classification'` reconciling with iterator-driven tests, at least one repaired test carrying a prompt-order comment) are already satisfied by the Task 1 commit. The full-suite sweep Task 3 also calls for (checking Phase 5/snapshot tests for other breakage) was run after Task 2 and found nothing further to fix — no `OnboardedHost` value-comparison or serialization test exists in the suite.

---

**Total deviations:** 1 auto-fixed (1 blocking — task-sequencing artifact of the plan's own verify dependency, no scope creep)
**Impact on plan:** No production behavior changed beyond what Tasks 1 and 2 already specified; only which task's commit carries the test-iterator fix.

## Issues Encountered

None beyond the sequencing note above.

## Verification Performed

- `uv run pytest tests/test_wizard.py -q` → 158 passed (after Task 1), 163 passed (after Task 2)
- `uv run pytest -q` (full suite) → 345 passed, 0 failed, 0 skipped (baseline was 337)
- `uvx ruff check --no-cache src/checkmk_wizard/wizard.py tests/test_wizard.py` → 3 findings, confirmed identical (same rule IDs, same line offsets after accounting for inserted lines) to a baseline run via `git stash` before any change in this plan — no new findings introduced
- `uvx ruff check --no-cache src/ tests/ scripts/` → 7 findings repo-wide, matching the stated pre-existing baseline exactly
- `grep -c '"tag_device_type"' src/checkmk_wizard/wizard.py` → 0 (key is derived from `DEVICE_TYPE_TAG_GROUP_ID` at exactly one place, `_device_type_and_alias_attributes`)
- `grep -c '_load_device_types()' src/checkmk_wizard/wizard.py` → 3 (definition, `_ensure_device_type_tag_group`, and the new Phase 4 prompt)
- Manually confirmed Phase 2 folder-default (`tests/test_wizard.py` line ~956, unchanged: `{"tag_agent": "no-agent", "tag_snmp_ds": "no-snmp"}`) and Phase 3 IP-placeholder (line ~756, unchanged: `{"ipaddress": ..., "tag_agent": "no-agent", "tag_snmp_ds": "no-snmp"}`) attribute assertions were not touched by this plan
- Not run: no live Checkmk site was available in this environment — all verification is against the mocked `respx`/`pytest` suite, consistent with this project's existing test-time convention (all external I/O mocked, no live-site integration tests exist)

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `OnboardedHost.device_type`/`.alias` and the Phase 5 `tag_device_type`/`alias` attributes are ready for plan 10-05's poller work (D-10: `scripts/mqtt_poller.py`'s Livestatus query needs the `alias` column) and for Phase 11's dashboard (alias-over-hostname display preference, deferred by design).
- No blockers.

---
*Phase: 10-checkmk-tag-group-onboarding-integration*
*Completed: 2026-09-11*

## Self-Check: PASSED

- FOUND: src/checkmk_wizard/wizard.py
- FOUND: tests/test_wizard.py
- FOUND: .planning/phases/10-checkmk-tag-group-onboarding-integration/10-04-SUMMARY.md
- FOUND: commit 2d38e3a
- FOUND: commit 27cda52
