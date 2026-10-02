# Phase 16 live UAT: gaps found (2026-10-02, deploy host, site dmc_test, demo hosts)

Passed so far: broker smoke test (all 7 live checks), A1 (active_checks_enabled present), /admin-config.json and /config.json, admin chrome only on ?admin=1, A2 (ctrl+click selects, no navigation), Set DOWN / Set UP on one and several hosts, confirm dialog lists only selected hosts, FAKED badge.

## Gaps (user-decided, to plan with `/bm:plan-phase 16 --gaps`)

1. **Plain click selects in admin mode.** In admin mode a plain click on a map node selects it (no host details); ctrl/cmd+click adds to the selection. Changes the Phase 16 design (plain click opened details).
2. **Select all.** Add a "Select all" next to "Clear selection" (respect current folder/filter so hidden hosts are not selected). Unselect-all already exists (Clear selection, Escape).
3. **Restore returns demo hosts to the demo baseline.** User decision: "Always demo baseline". Restore = host UP + PING OK result (same text as Set UP), PING check stays DISABLED, host check re-enabled (the "Always assume host to be up" rule keeps it UP). Today Restore sends ENABLE_SVC_CHECK;<host>;PING, which makes Checkmk really ping a non-existent IP, so PING goes CRITICAL. Restore all follows the same rule. Faked-set derivation (host check disabled AND PING disabled/absent) must still work: after restore the host check is enabled, so the host is not counted as faked. Do NOT add forced checks to Restore (would make hosts CRITICAL faster).
   Also correct docs: "Incident demo with fake check results.md" and the 16-07 text claim Restore on demo hosts returns UP; update `fakeping ... restore` accordingly.

## Not yet verified
Steps 8 (cascade, A4), 9 (inferred switch card, D-03), 10 (folder selection incl. subfolders, OQ3), 11 (persistence across full down/up, D-10), 12 (Restore all), 13 (demo hosts not counted as faked), 14 (no-answer timeout). Banner count not explicitly confirmed.
