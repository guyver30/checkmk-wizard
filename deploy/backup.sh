#!/usr/bin/env bash
# Back up everything needed to rebuild this stack's Checkmk site and topology
# map on another machine, into ONE tar bundle:
#   checkmk        the Checkmk site (see the two modes below)
#   map_drawing    the topology map's shared drawing layer (map_drawing_data)
#   env            a copy of deploy/.env (CMK_SITE_ID and the secrets the
#                  restored site was created with; without it the restored
#                  automation / topology_editor users no longer match)
#   manifest.txt   mode, site id, project, checkmk image, date
#
# Usage: deploy/backup.sh [--no-history] [--out DIR]
#   (default)      WITH history: export the whole checkmk_data volume (hosts,
#                  rules, users, RRDs, logs, agent registrations). Does a full
#                  `compose down` / `up -d` so the volume is quiescent.
#   --no-history   config only: `omd backup --no-rrds --no-past` run inside the
#                  running checkmk container. No downtime. Restores into a
#                  fresh site with no metric/availability history.
#   --out DIR      where to write the bundle (default: current directory)
#
# The bundle holds secrets (it contains .env): it is written mode 600. Restore
# with deploy/restore_backup.sh.
#
# Always a full down/up: restarting a single container once cut Checkmk off
# from the LAN (Podman setup doc §5.1).

set -euo pipefail

with_history=true
out_dir="$PWD"
while [ $# -gt 0 ]; do
    case "$1" in
        --no-history) with_history=false ;;
        --out)
            if [ $# -lt 2 ]; then echo "--out needs a DIR (see --help)" >&2; exit 2; fi
            out_dir="$2"; shift ;;
        -h|--help) sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done
mkdir -p "$out_dir"
out_dir="$(cd "$out_dir" && pwd)"

# compose.yaml and .env live here, and the directory name is the compose
# project name that prefixes the volume names (deploy_checkmk_data, ...).
cd "$(dirname "${BASH_SOURCE[0]}")"
project="${COMPOSE_PROJECT_NAME:-$(basename "$PWD")}"

if [ ! -f .env ]; then
    echo "deploy/.env not found; nothing to back up against." >&2
    exit 1
fi
site="$(sed -n 's/^CMK_SITE_ID=//p' .env | tail -1)"
site="${site:-dmc}"

for vol in checkmk_data map_drawing_data; do
    if ! podman volume exists "${project}_${vol}"; then
        echo "Volume ${project}_${vol} not found (run from the deploy/ directory of the stack you want to back up)." >&2
        exit 1
    fi
done

mode=$($with_history && echo full || echo nohistory)
stamp="$(date +%Y%m%d-%H%M%S)"
bundle="$out_dir/checkmk-backup-${site}-${stamp}-${mode}.tar"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
umask 077

if $with_history; then
    echo "Stopping the stack (full down) to export checkmk_data consistently..."
    podman compose down
    podman volume export "${project}_checkmk_data" -o "$work/checkmk_data.tar"
else
    if ! podman exec checkmk omd status "$site" >/dev/null 2>&1; then
        echo "The checkmk container is not running site '$site'; start the stack first (or omit --no-history)." >&2
        exit 1
    fi
    echo "Running omd backup (no RRDs, no past monitoring data)..."
    podman exec checkmk omd backup --no-rrds --no-past "$site" - > "$work/site.omd.tar"
fi

podman volume export "${project}_map_drawing_data" -o "$work/map_drawing_data.tar"
cp .env "$work/env"
{
    echo "mode=$mode"
    echo "site=$site"
    echo "project=$project"
    echo "created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "checkmk_image=$(podman inspect checkmk --format '{{.ImageName}}' 2>/dev/null || sed -n '/^  checkmk:/,/image:/s/^ *image: *//p' compose.yaml | tail -1)"
} > "$work/manifest.txt"

tar -C "$work" -cf "$bundle" .
chmod 600 "$bundle"

if $with_history; then
    echo "Starting the stack again..."
    podman compose up -d
fi

echo
echo "Backup written: $bundle ($(du -h "$bundle" | cut -f1), mode $mode)"
echo "It contains deploy/.env (secrets); store it accordingly."
