#!/usr/bin/env bash
# Rebuild the dashboard and worker images, then bring the whole stack down and up
# again, so a `git pull` is actually picked up (the poller reads
# scripts/mqtt_poller.py once at start, and analytics bind-mounts the repo).
#
# A full down/up is deliberate, not a single-container restart: that has cut
# Checkmk's egress before (docs/DEPLOY-NEW-MACHINE.md §11.1, "Updating later").
#
# Usage: deploy/redeploy.sh
set -euo pipefail

# compose.yaml and .env live next to this script, and the directory name sets the
# compose project (and so the volume names).
cd "$(dirname "$0")"

# The dashboard and worker have build: sections (the worker image bakes in uv and the
# wizard's dependencies so it runs offline; unchanged layers are cached and need no
# network). Poller and analytics run stock python images with the repo bind-mounted;
# `down` removes their containers, so the `up -d` below creates them fresh and they
# pick up new code. (An earlier version also ran `up -d --force-recreate poller
# analytics` between the two: after `down` there is nothing to recreate, and
# podman-compose 1.0.6 only printed exit 125/1 "no such container" errors for it.)
podman compose build dashboard worker
podman compose down
podman compose up -d
