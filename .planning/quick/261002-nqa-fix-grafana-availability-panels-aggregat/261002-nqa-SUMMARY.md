---
status: complete
---
# Quick 261002-nqa: Availability dashboard "per device / per folder over range" illegal_aggregation

Symptom (live, Phase 14.1 plan 08 step 8): both panels failed with code 184 ILLEGAL_AGGREGATION "aggregate function sum(up_minutes) AS up_minutes is found inside another aggregate function".
Cause: the SELECT aliases `sum(up_minutes) AS up_minutes` (alias = column name) and then computes `availability_pct` with `sum(up_minutes)` again; ClickHouse resolves that inner name to the alias, so the aggregate is nested.
Fix: `availability_pct` now uses the aliases (`round(up_minutes / nullIf(up_minutes + down_minutes, 0) * 100, 3)`) in both panels in `deploy/grafana-provisioning/dashboards/json/availability.json`. The other self-aliased aggregates in the three dashboards do not reuse the alias inside another aggregate, and they rendered.
The "Fleet availability % per day" panel being empty is expected: `history.availability_daily` has no rows until the first daily rollup (needs a finished Singapore day).
Not verified live: no ClickHouse here; check on the deploy host with the query in the chat/runbook and by reloading the dashboard.
