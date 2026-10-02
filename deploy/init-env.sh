#!/usr/bin/env bash
# Prepare deploy/.env for a new machine: generate every secret the stack needs,
# ask for the Checkmk site name, and let the operator pick this machine's LAN
# address from its interfaces. Values already set in .env are never overwritten,
# so the script is safe to re-run.
#
# Generated: CMK_REST_SECRET, TOPOLOGY_EDITOR_SECRET, CH_ADMIN_PASSWORD,
#            CH_WRITER_PASSWORD, CH_READER_PASSWORD, CH_GRAFANA_PASSWORD,
#            GRAFANA_ADMIN_PASSWORD, MQTT_POLLER_PASSWORD, WS_PASSWORD,
#            ADMIN_WS_PASSWORD
# Asked:     CMK_SITE_ID (default dmc), CMK_PUBLIC_HOST
#
# Secrets are 32 URL-safe characters ([A-Za-z0-9_-]), which also satisfies
# deploy/clickhouse-config/initdb/02-users.sh (no quotes, backslash or
# whitespace). Run it BEFORE the first `podman compose up`: the site name and
# the ClickHouse passwords only take effect when their volumes are created.
#
# Usage: deploy/init-env.sh

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
env_file=.env

if [ ! -f "$env_file" ]; then
    cp .env.example "$env_file"
    echo "Created $env_file from .env.example."
fi
chmod 600 "$env_file"

# Last active (uncommented) KEY=value line wins, as with compose.
get_val() {
    sed -n "s/^$1=//p" "$env_file" | tail -1
}

# Set KEY only where .env has it empty or missing. Reuses an existing `KEY=`
# or `# KEY=...` line so the comments from .env.example stay next to it.
# Values are restricted to [A-Za-z0-9_.:-], so no sed escaping is needed.
set_val() {
    local key="$1" value="$2"
    if grep -q "^$key=" "$env_file"; then
        sed -i "s|^$key=.*|$key=$value|" "$env_file"
    elif grep -q "^# *$key=" "$env_file"; then
        sed -i "0,/^# *$key=.*/s||$key=$value|" "$env_file"
    else
        printf '%s=%s\n' "$key" "$value" >> "$env_file"
    fi
}

gen_secret() {
    head -c 24 /dev/urandom | base64 | tr '+/' '-_' | tr -d '=\n'
}

summary=()

for key in CMK_REST_SECRET TOPOLOGY_EDITOR_SECRET CH_ADMIN_PASSWORD CH_WRITER_PASSWORD \
    CH_READER_PASSWORD CH_GRAFANA_PASSWORD GRAFANA_ADMIN_PASSWORD MQTT_POLLER_PASSWORD \
    WS_PASSWORD ADMIN_WS_PASSWORD; do
    if [ -n "$(get_val "$key")" ]; then
        summary+=("$key: kept")
    else
        set_val "$key" "$(gen_secret)"
        summary+=("$key: generated")
    fi
done

# Same rule as the wizard's _SITE_NAME_RE: starts with a letter, letters,
# digits and underscores only, at most 16 characters.
site="$(get_val CMK_SITE_ID)"
if [ -n "$site" ]; then
    summary+=("CMK_SITE_ID: kept ($site)")
else
    if podman volume exists "$(basename "$PWD")_checkmk_data" 2>/dev/null; then
        echo "Note: a checkmk_data volume already exists; its site keeps its old name"
        echo "unless you remove the volume (deploy/reset-site.sh)."
    fi
    while true; do
        read -r -p "Checkmk site name [dmc]: " site
        site="${site:-dmc}"
        if [[ "$site" =~ ^[A-Za-z][A-Za-z0-9_]{0,15}$ ]]; then
            break
        fi
        echo "Invalid: start with a letter; letters, digits, underscores; max 16 characters."
    done
    set_val CMK_SITE_ID "$site"
    summary+=("CMK_SITE_ID: set ($site)")
fi

public_host="$(get_val CMK_PUBLIC_HOST)"
if [ -n "$public_host" ]; then
    summary+=("CMK_PUBLIC_HOST: kept ($public_host)")
else
    # Global-scope IPv4 addresses, minus container bridges and veth pairs:
    # agents must reach the host's LAN address, not a 10.89.x.x Podman one.
    mapfile -t choices < <(
        ip -4 -o addr show scope global 2>/dev/null |
            awk '$2 !~ /^(podman|cni-|br-|docker|veth|virbr)/ {split($4, a, "/"); print a[1] "  (" $2 ")"}'
    )
    choices+=("Enter an address or DNS name by hand")
    echo "Which address do the monitored hosts use to reach this machine?"
    PS3="Select 1-${#choices[@]}: "
    select choice in "${choices[@]}"; do
        if [ -z "${choice:-}" ]; then
            continue
        fi
        if [ "$REPLY" -eq "${#choices[@]}" ]; then
            while true; do
                read -r -p "Address or DNS name: " public_host
                if [[ "$public_host" =~ ^[A-Za-z0-9][A-Za-z0-9.:-]*$ ]]; then
                    break
                fi
                echo "Invalid: letters, digits, dots, colons and hyphens only."
            done
        else
            public_host="${choice%%  *}"
        fi
        break
    done
    set_val CMK_PUBLIC_HOST "$public_host"
    summary+=("CMK_PUBLIC_HOST: set ($public_host)")
fi

echo
echo "deploy/.env (secret values are not printed):"
printf '  %s\n' "${summary[@]}"
cat <<EOF

Next steps:
  cd deploy && podman compose down && podman compose up -d
  (a full down/up, never a single-service restart -- see the project memory
  about single-container restarts breaking Checkmk egress)
  \`podman compose build dashboard\` is only needed after pulling code changes.

  To rotate a Mosquitto password (MQTT_POLLER_PASSWORD, WS_PASSWORD or ADMIN_WS_PASSWORD),
  edit it in deploy/.env, then \`podman compose down && podman compose up -d\`
  -- the mosquitto container rebuilds its password file from .env on every
  start. Note: an existing .env with WS_PASSWORD=wsreader already uncommented
  keeps that value (this script never overwrites a set value) -- blank it out
  and re-run this script to get a generated one instead.
  Existing installs must re-run this script before `podman compose up`:
  compose refuses to start mosquitto and dashboard without ADMIN_WS_PASSWORD.
EOF
