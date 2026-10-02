---
status: complete
---
# Quick 261002-liq — Summary

- `deploy/compose.yaml`: removed `depends_on: minio` from `minio-init`, with a comment explaining why (podman-compose 1.0.6 `--requires` chain: clickhouse -> minio-init -> minio, minio already running so absent from podman's start list -> "not found in input list").
- `docs/DEPLOY-NEW-MACHINE.md` §5: added the symptom and the stop-and-start workaround.
- Checked: compose YAML parses; `minio-init` has no depends_on, clickhouse still depends on minio + minio-init, grafana on clickhouse.
- **Confirmed live 2026-10-02 (user, deploy host):** a full `podman compose down && up -d` after pulling this change gave exit code 0 for every container (earlier runs gave 125/127 for clickhouse and grafana). Originally listed as not verified:
- **Not verified live (superseded by the line above)** (no stack here): confirm on the deploy host with a full `podman compose down && podman compose up -d`; `podman ps` should show nothing stuck in `Created`. The root cause is inferred from podman's error text, not reproduced.
