#!/usr/bin/env bash
# Rebuild the dashboard and analytics images, then bring the whole stack down and
# up again with the poller and analytics force-recreated, so a `git pull` is
# actually picked up (the poller reads scripts/mqtt_poller.py once at start).
#
# A full down/up is deliberate, not a single-container restart: that has cut
# Checkmk's egress before (docs/DEPLOY-NEW-MACHINE.md, "Updating later").
#
# Usage: deploy/redeploy.sh
set -euo pipefail

# compose.yaml and .env live next to this script, and the directory name sets the
# compose project (and so the volume names).
cd "$(dirname "$0")"

podman compose build dashboard analytics
podman compose down
podman compose up -d --force-recreate poller analytics
# `up -d` with service names starts only those and their dependencies; this starts
# the rest (already-running services are left as they are).
podman compose up -d
