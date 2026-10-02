---
status: complete
---
# Quick 261002-nm2: raise the read-only ClickHouse profile's max_execution_time cap

Symptom (live, Phase 14.1 plan 08 step 8): every panel of all three Grafana dashboards failed with code 452 SETTING_CONSTRAINT_VIOLATION "setting max_execution_time shouldn't be greater than 60".
Cause: `history_reader_profile` (used by grafana_reader and dashboard_reader) had `max_execution_time = 30 MAX 60 CHANGEABLE_IN_READONLY`, and Grafana's client sends its own max_execution_time above 60 (inferred from the error; the exact value sent was not observed).
Fix: `MAX 120` in `deploy/clickhouse-config/initdb/02-users.sh` (new installs) and a one-off `ALTER SETTINGS PROFILE` for existing hosts, documented in `docs/DEPLOY-NEW-MACHINE.md`.
Not verified live: run the ALTER on the deploy host and reload the Grafana dashboards.
