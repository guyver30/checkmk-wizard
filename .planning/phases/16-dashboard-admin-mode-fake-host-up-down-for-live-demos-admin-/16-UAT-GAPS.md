# Phase 16 live UAT: gaps found (2026-10-02, deploy host, site dmc_test, demo hosts)

Passed so far: broker smoke test (all 7 live checks), A1 (active_checks_enabled present), /admin-config.json and /config.json, admin chrome only on ?admin=1, A2 (ctrl+click selects, no navigation), Set DOWN / Set UP on one and several hosts, confirm dialog lists only selected hosts, FAKED badge.

## Gaps (user-decided, to plan with `/bm:plan-phase 16 --gaps`)

1. **Plain click selects in admin mode.** In admin mode a plain click on a map node selects it (no host details); ctrl/cmd+click adds to the selection. Changes the Phase 16 design (plain click opened details).
2. **Select all.** Add a "Select all" next to "Clear selection" (respect current folder/filter so hidden hosts are not selected). Unselect-all already exists (Clear selection, Escape).
3. **Restore returns demo hosts to the demo baseline.** User decision: "Always demo baseline". Restore = host UP + PING OK result (same text as Set UP), PING check stays DISABLED, host check re-enabled (the "Always assume host to be up" rule keeps it UP). Today Restore sends ENABLE_SVC_CHECK;<host>;PING, which makes Checkmk really ping a non-existent IP, so PING goes CRITICAL. Restore all follows the same rule. Faked-set derivation (host check disabled AND PING disabled/absent) must still work: after restore the host check is enabled, so the host is not counted as faked. Do NOT add forced checks to Restore (would make hosts CRITICAL faster).
   Also correct docs: "Incident demo with fake check results.md" and the 16-07 text claim Restore on demo hosts returns UP; update `fakeping ... restore` accordingly.

3b. **Reverse cascade hits the same defect.** Set UP on a managed switch restores its cascaded children with the "restore" op (`plan_admin_actions`, cascade_op = "restore"), so they get ENABLE_SVC_CHECK PING and go CRITICAL and never recover (user saw this). Fixed by gap 3 if the cascade restore uses the demo baseline too.

4. **Faked hosts go stale after ~3 minutes.** Live data (check_interval 1 min): every host with active_checks_enabled=0 (faked DOWN/UNREACH/UP) had staleness 2.9 to 11.2 and growing, every host with checks enabled had 0.83. A fake injects one result and nothing refreshes it, so Checkmk `staleness` (age / check_interval) passes the dashboard's STALENESS_FACTOR of 3 after ~3 minutes. Set UP is also a fake (checks stay disabled), so UP hosts go stale too. Poller logs were healthy (every command applied; the 401 and ClickHouse warnings were only in the first minutes after startup).
   User-approved fix: the poller periodically re-injects each faked host's current state (same PROCESS_HOST_CHECK_RESULT / PROCESS_SERVICE_CHECK_RESULT, state taken from the faked set) at least every 60 s, so staleness stays near 0 while faked. Hosts that are not faked are untouched.

## Not yet verified
Step 12 (Restore all, blocked by gap 3), 13 (demo hosts not counted as faked), 14 (no-answer timeout). Steps 8 (cascade, A4), 9 (inferred switch card, D-03), 10 (folders, OQ3) and 11 (persistence, D-10) passed per the user. Banner count not explicitly confirmed.
