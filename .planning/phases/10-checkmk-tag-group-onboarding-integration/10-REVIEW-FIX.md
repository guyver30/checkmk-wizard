---
phase: 10-checkmk-tag-group-onboarding-integration
fixed: 2026-09-11
status: complete
findings_addressed: 5
findings_rejected: 1
findings_deferred: 14
tests_before: 348
tests_after: 357
---

# Phase 10 — Code Review Fixes

All 5 verified critical findings fixed. Each fix carries a regression test that was
**confirmed to fail against the unfixed code** before being committed (by selectively
reverting that fix and re-running the test), not merely asserted to.

## Fixed

| ID | Commit | Problem | Fix |
|----|--------|---------|-----|
| CR-01 | `e6d92bc` | `${CMK_REST_SECRET:?}` is interpolated at compose **parse** time, so it blocked `up -d checkmk`/`mosquitto` too — a fresh-install deadlock, since the automation secret only exists after a wizard run against a live site | `${CMK_REST_SECRET:-}`; the poller already degrades when the credential is absent (10-03's design). Setup doc §3's now-false "compose refuses to start" claim corrected |
| CR-02 | `47d1538` | `get_host_tag_group` sat outside `_ensure_device_type_tag_group`'s `try`, so a 401/500/connect error propagated through `phase2_folders` and aborted the whole run — while the docstring claimed otherwise | Probe moved inside the `try`, so the documented contract holds |
| CR-03 | `47d1538` | Provisioning returned `None` on success *and* failure while Phase 5 sent `tag_device_type` unconditionally ⇒ every `create_host` 400s ⇒ **zero hosts onboarded**, as N opaque per-host warnings | Returns `bool`, threaded `phase2 → run → phase5 → _onboard_hosts` to all 3 call sites. Degrades to onboarding without the tag, one clear warning; `alias` still applied |
| CR-04 | `e94d6c8` | `--once` omitted `folders=`, publishing retained `status` *and* `topology` with every folder blanked over correct values. No `--once` coverage existed at all | Fetches the folder map like `run_forever`, degrading on `RestError` |
| CR-06 | `e94d6c8` | The `78ff087` crash-loop fix handled missing keys but not wrong types, leaving the contract it cited broken: `{"id": ["x"]}` → uncaught `TypeError` inside `parse_topology_payload`; `parents: "r1"` → `sorted()` character-exploded signature | Type-check with `isinstance` (matching `query_devices`); non-`str` `id` skipped, wrong types fall back to defaults |

Two of these (CR-01, CR-06) were regressions introduced during this phase's own
orchestration, not by the plan executors.

## Rejected — verified false positive

**CR-05** claimed `ArgumentDefaultsHelpFormatter` + `default=os.environ.get("CMK_REST_SECRET")`
makes `--help` print the live secret. It does not: that formatter only appends `(default: …)`
to an **existing** `help=` string, and none of the probe's arguments define one.

Verified by execution:
`CMK_REST_SECRET='SUPERSECRET123' uv run python scripts/probe_checkmk_rest_shapes.py --help | grep -c SUPERSECRET123` → `0`.

`scripts/probe_checkmk_rest_shapes.py` was deliberately left unmodified. Adding `help=` text
to those arguments would have *created* the leak the finding imagined.

## Deferred — out of scope for this pass

The 11 warnings and 3 info findings in `10-REVIEW.md` were not addressed. The highest-value
ones to triage next:

- **WR-03** — `folder=""` is overloaded (root folder / host absent / fetch failed), so
  `check_device_enrichment` false-FAILs the *default* wizard path (folders declined) with a
  misleading "missing CMK_REST_SECRET" diagnosis.
- **WR-04** — a 200-but-empty REST response overwrites `last_folders` with `{}`, defeating the
  T-10-12 reuse guard without logging anything.
- **WR-07** — `_load_device_types()` is re-read per host inside the Phase 4 loop, so a
  `ValueError` aborts after prompts are already answered.
- **WR-09** — the docs' "`alias` is empty for any host without one" claim is the one assumption
  stated as fact with no live observation behind it (the live run showed Checkmk defaults an
  alias to the hostname).

The 7 pre-existing repo-wide ruff findings were left alone — they predate this phase.

## Gates after fixes

- `uv run pytest -q` → **357 passed** (was 348; +9 regression tests)
- `uvx ruff check --no-cache src/ tests/ scripts/` → exactly **7** pre-existing findings, unchanged
- `grep -c ':?' deploy/compose.yaml` → 0; compose still parses as valid YAML
- `extract_device_type`'s live-verified bare-key-only behaviour preserved
