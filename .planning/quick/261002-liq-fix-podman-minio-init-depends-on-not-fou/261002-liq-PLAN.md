# Quick 261002-liq: minio-init depends_on breaks fresh `podman compose up -d`

Remove `depends_on: minio` from `minio-init` in `deploy/compose.yaml` (its entrypoint already retries `mc alias set`), keep clickhouse/grafana dependencies, document the stop-and-start workaround in `docs/DEPLOY-NEW-MACHINE.md`.
Run inline (no planner/executor agents): three-line change plus one doc note.
