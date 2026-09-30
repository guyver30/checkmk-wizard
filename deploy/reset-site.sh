#!/usr/bin/env bash
# Start over with a blank Checkmk site in container mode: stop the stack,
# delete the site volume and the broker's retained-message volume, start again.
#
# The worker has no `omd`, so the wizard itself cannot delete a site; the
# checkmk entrypoint creates a new, empty site on the next start when the
# `checkmk_data` volume is gone. `mosquitto_data` goes too, because the
# poller's startup sweep does not clear the global `lan/events/recent` feed
# (docs/WIZARD-OPERATION.md, "Starting over with a blank site").
#
# Usage: deploy/reset-site.sh [--with-history] [--yes]
#   --with-history  also delete ClickHouse history (clickhouse_data)
#   --yes           skip the confirmation prompt
#
# Always a full down/up: restarting a single container once cut Checkmk off
# from the LAN (Podman setup doc §5.1).

set -euo pipefail

with_history=false
assume_yes=false
for arg in "$@"; do
    case "$arg" in
        --with-history) with_history=true ;;
        --yes) assume_yes=true ;;
        -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
    esac
done

# compose.yaml and .env live here, and the directory name is the compose
# project name that prefixes the volume names (deploy_checkmk_data, ...).
cd "$(dirname "${BASH_SOURCE[0]}")"
project="${COMPOSE_PROJECT_NAME:-$(basename "$PWD")}"
site="$(sed -n 's/^CMK_SITE_ID=//p' .env 2>/dev/null | tail -1)"
site="${site:-dmc}"

volumes=("${project}_checkmk_data" "${project}_mosquitto_data")
if $with_history; then
    volumes+=("${project}_clickhouse_data")
fi

echo "This deletes the Checkmk site '$site' (hosts, folders, rules, users,"
echo "monitoring history) and the dashboard's retained MQTT data. No undo."
echo "Volumes: ${volumes[*]}"
if ! $assume_yes; then
    read -r -p "Type the site name to confirm: " answer
    if [ "$answer" != "$site" ]; then
        echo "Aborted." >&2
        exit 1
    fi
fi

podman compose down

for vol in "${volumes[@]}"; do
    if podman volume exists "$vol"; then
        podman volume rm "$vol"
    else
        echo "Volume $vol not found, skipping (check 'podman volume ls')."
    fi
done

podman compose up -d

echo "Waiting for the new site to answer on http://localhost:8080/$site/ ..."
for _ in $(seq 1 60); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:8080/$site/check_mk/" || true)"
    if [ "$code" = "302" ] || [ "$code" = "200" ]; then
        break
    fi
    sleep 5
done
echo "Checkmk HTTP status: ${code:-none} (expect 302)"
echo "LIVESTATUS_TCP_TLS: $(podman compose exec checkmk omd config "$site" show LIVESTATUS_TCP_TLS 2>/dev/null || echo '?') (expect off)"

cat <<EOF

Next:
  1. On every previously onboarded Linux host, run: cmk-agent-ctl delete-all
  2. Run the wizard: deploy/run-wizard.sh
  3. Hard-refresh the dashboard (Ctrl+Shift+R).
EOF
