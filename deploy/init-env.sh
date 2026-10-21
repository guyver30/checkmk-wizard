#!/usr/bin/env bash
# Prepare deploy/.env for a new machine: generate every secret the stack needs,
# ask for the Checkmk site name, and let the operator pick this machine's LAN
# address from its interfaces. Values already set in .env are never overwritten,
# so the script is safe to re-run.
#
# Generated: CMK_REST_SECRET, TOPOLOGY_EDITOR_SECRET, CH_ADMIN_PASSWORD,
#            CH_WRITER_PASSWORD, CH_READER_PASSWORD, CH_GRAFANA_PASSWORD,
#            GRAFANA_ADMIN_PASSWORD, MQTT_POLLER_PASSWORD, WS_PASSWORD,
#            ADMIN_WS_PASSWORD, MQTT_ANALYTICS_PASSWORD, TRIAGE_WS_PASSWORD,
#            CH_ANALYTICS_PASSWORD, MQTT_BRIDGE_PASSWORD
# Defaults written explicitly: WS_USERNAME=wsreader, ADMIN_WS_USERNAME=wsadmin,
#            TRIAGE_WS_USERNAME=wstriage, CLICKHOUSE_TAG=26.9.4.3 (see below)
# Asked:     CMK_SITE_ID (default dmc), CMK_PUBLIC_HOST
# Not set here: SITE_SEN (the wizard writes it) and the cloud feed settings
#            (CLOUD_BROKER_HOST, CLOUD_BROKER_PASSWORD come from the cloud operator).
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
    WS_PASSWORD ADMIN_WS_PASSWORD MQTT_ANALYTICS_PASSWORD TRIAGE_WS_PASSWORD \
    CH_ANALYTICS_PASSWORD MQTT_BRIDGE_PASSWORD; do
    if [ -n "$(get_val "$key")" ]; then
        summary+=("$key: kept")
    else
        set_val "$key" "$(gen_secret)"
        summary+=("$key: generated")
    fi
done

# Compose defaults that must be real values in .env. 2026-10-21: with the
# podman-compose a fresh machine had, `- WS_USERNAME=${WS_USERNAME:-wsreader}`
# in the dashboard's `environment:` reached the container as the literal text
# `${WS_USERNAME:-wsreader}` when WS_USERNAME was not in .env, and nginx
# refused to start ("the closing bracket in "WS_USERNAME" variable is
# missing") when envsubst pasted it into /config.json. Writing the values the
# defaults stand for sidesteps default expansion entirely. Existing values
# (including a CLICKHOUSE_TAG override) are kept.
for pair in WS_USERNAME=wsreader ADMIN_WS_USERNAME=wsadmin \
    TRIAGE_WS_USERNAME=wstriage CLICKHOUSE_TAG=26.9.4.3; do
    key="${pair%%=*}"
    if [ -n "$(get_val "$key")" ]; then
        summary+=("$key: kept ($(get_val "$key"))")
    else
        set_val "$key" "${pair#*=}"
        summary+=("$key: set (${pair#*=})")
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
    echo "Note: the site name is also the MQTT namespace (sites/<name>/... on the broker)"
    echo "and must be globally unique per broker; changing it later moves the namespace."
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
echo
echo "Existing installs must re-run this script before 'podman compose up':"
echo "compose refuses to start mosquitto and dashboard without ADMIN_WS_PASSWORD."
