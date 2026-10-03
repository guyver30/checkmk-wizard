---
status: complete
---
# Quick 261003-le3 summary

Added `GRANT CREATE TEMPORARY TABLE ON *.* TO poller_writer;` to `02-users.sh` and documented the
one-off command for existing hosts (DEPLOY-NEW-MACHINE.md section 6) plus the Podman doc privilege row.

Live-verified on dmc-server 2026-10-03: after the manual GRANT the poller logged
"Availability rollup written for 2026-10-02 (JSON + Parquet)", the smoke test passed 12/12, and a full
compose down/up left both rollup objects (ETag, Last-Modified) unchanged. `bash -n` on `02-users.sh` ok.
The initdb script itself was not re-run (it only runs on a fresh volume).
