#!/usr/bin/env bash
# Start over with a blank Checkmk site in container mode, optionally under a
# new name: detect the site that really lives in the site volume, confirm it,
# ask for the new site name, then stop the stack, delete the site volume and
# the broker's retained-message volume, record the name in deploy/.env and
# start again.
#
# The worker has no `omd`, so the wizard itself cannot delete a site; the
# checkmk entrypoint creates a new, empty site on the next start when the
# `checkmk_data` volume is gone, named after CMK_SITE_ID. `mosquitto_data` goes
# too, because the poller's startup sweep does not clear the global
# `lan/events/recent` feed (docs/WIZARD-OPERATION.md, "Starting over with a
# blank site").
#
# Usage: deploy/reset-site.sh [--with-history] [--yes] [--site NAME]
#   --with-history  also delete ClickHouse history (clickhouse_data)
#   --yes           skip both prompts and keep the current name
#   --site NAME     new site name; with --yes it renames non-interactively,
#                   without --yes it is the default of the new-name prompt
# Esc or Ctrl+C at either prompt aborts before anything is changed.
#
# Always a full down/up: restarting a single container once cut Checkmk off
# from the LAN (Podman setup doc §5.1).

set -euo pipefail

site_re='^[A-Za-z][A-Za-z0-9_]{0,15}$'
site_invalid_msg="Invalid: start with a letter; letters, digits, underscores; max 16 characters."

with_history=false
assume_yes=false
site_arg=""
while [ $# -gt 0 ]; do
    case "$1" in
        --with-history) with_history=true ;;
        --yes) assume_yes=true ;;
        --site)
            if [ $# -lt 2 ]; then echo "--site needs a NAME (see --help)" >&2; exit 2; fi
            site_arg="$2"; shift ;;
        -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

if [ -n "$site_arg" ] && ! [[ "$site_arg" =~ $site_re ]]; then
    echo "--site '$site_arg'. $site_invalid_msg" >&2
    exit 2
fi

# compose.yaml and .env live here, and the directory name is the compose
# project name that prefixes the volume names (deploy_checkmk_data, ...).
cd "$(dirname "${BASH_SOURCE[0]}")"
project="${COMPOSE_PROJECT_NAME:-$(basename "$PWD")}"
env_file=.env

# Same helpers as init-env.sh: replace the line, else uncomment the
# `# KEY=` line from .env.example, else append.
get_val() { sed -n "s/^$1=//p" "$env_file" 2>/dev/null | tail -1; }
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

abort() {
    echo >&2
    echo "Aborted." >&2
    exit 1
}

# Line reader that treats Esc (and EOF) as abort, which plain `read -p` cannot.
# read_line PROMPT VARNAME [DEFAULT]
read_line() {
    local prompt="$1" var="$2" default="${3:-}" buf="" ch
    printf '%s' "$prompt" >&2
    while true; do
        IFS= read -rsn1 ch || abort
        case "$ch" in
            "") break ;;
            $'\e')
                # Swallow the tail of an arrow-key sequence, then abort anyway.
                read -rsn5 -t 0.05 _ || true
                abort ;;
            $'\x7f'|$'\b')
                if [ -n "$buf" ]; then
                    buf="${buf%?}"
                    printf '\b \b' >&2
                fi ;;
            *)
                buf+="$ch"
                printf '%s' "$ch" >&2 ;;
        esac
    done
    echo >&2
    printf -v "$var" '%s' "${buf:-$default}"
}

# 1. Pre-flight: nothing is asked or changed unless compose can parse .env.
# `config --services`, not `config -q`: podman-compose 1.0.6 (Debian/Ubuntu
# package) has no -q and failed this check on a complete .env (2026-10-01).
# The compose error is shown, so a real cause is never hidden behind the hint.
if ! config_err="$(podman compose config --services 2>&1 >/dev/null)"; then
    echo "$config_err" >&2
    echo "Compose could not read deploy/compose.yaml with deploy/.env (error above)." >&2
    echo "If it names a missing variable, run deploy/init-env.sh first." >&2
    exit 1
fi

volumes=("${project}_checkmk_data" "${project}_mosquitto_data")
if $with_history; then
    volumes+=("${project}_clickhouse_data")
fi

# 2. Detect the site that really exists in the volume. .env only says what the
# NEXT start will create, so it can disagree with what is on disk.
env_site="$(get_val CMK_SITE_ID)"
env_site="${env_site:-dmc}"
existing_site="$env_site"
if ! podman volume exists "${project}_checkmk_data"; then
    echo "Volume ${project}_checkmk_data does not exist: no site to delete."
else
    listing=""
    if [ "$(podman container inspect -f '{{.State.Running}}' checkmk 2>/dev/null || true)" = "true" ]; then
        listing="$(podman exec checkmk ls /omd/sites 2>/dev/null || true)"
    else
        # Throwaway container from the image already on this machine
        # (--pull=never), volume read-only, so detection changes nothing.
        image="$(sed -n 's/^ *image: *\(checkmk\/.*\)$/\1/p' compose.yaml | head -1)"
        listing="$(podman run --rm --pull=never --entrypoint ls \
            -v "${project}_checkmk_data:/omd/sites:ro" "$image" /omd/sites 2>/dev/null || true)"
    fi
    # Drops lost+found and anything else that is not a valid site name.
    found=()
    while IFS= read -r name; do
        if [[ "$name" =~ $site_re ]]; then found+=("$name"); fi
    done <<< "$listing"
    if [ "${#found[@]}" -eq 0 ]; then
        echo "WARNING: could not detect the site in the volume; assuming '$env_site' from deploy/.env."
    else
        existing_site="${found[0]}"
        for name in "${found[@]}"; do
            if [ "$name" = "$env_site" ]; then existing_site="$env_site"; fi
        done
        if [ "${#found[@]}" -gt 1 ]; then
            echo "Sites in volume: ${found[*]}"
        fi
    fi
fi
echo "Site in volume:              $existing_site"
echo "CMK_SITE_ID in deploy/.env:  $env_site"
if [ "$existing_site" != "$env_site" ]; then
    echo "WARNING: they differ. The volume's name ('$existing_site') is what exists now;"
    echo "         .env only decides the name of the next site."
fi

echo
echo "This deletes the Checkmk site '$existing_site' (hosts, folders, rules, users,"
echo "monitoring history) and the dashboard's retained MQTT data. No undo."
echo "Volumes: ${volumes[*]}"

# Nothing has been modified yet, so Ctrl+C here is a clean abort.
trap 'abort' INT

# 3. Confirm the existing name, then ask for the new one.
if ! $assume_yes; then
    read_line "Type the site name to confirm: " answer
    # shellcheck disable=SC2154  # assigned by read_line via printf -v
    if [ "$answer" != "$existing_site" ]; then
        abort
    fi
fi

new_site="${site_arg:-$existing_site}"
if ! $assume_yes; then
    while true; do
        read_line "New site name [$new_site]: " candidate "$new_site"
        # shellcheck disable=SC2154  # assigned by read_line via printf -v
        if [[ "$candidate" =~ $site_re ]]; then
            new_site="$candidate"
            break
        fi
        echo "$site_invalid_msg" >&2
    done
fi
if [ "$new_site" != "$existing_site" ]; then
    echo "Renaming '$existing_site' -> '$new_site'; agents must re-register (see Next: below)."
fi

trap - INT

# 4. Changes. The name goes into .env before `up -d` so the entrypoint creates
# the new site under it.
podman compose down

for vol in "${volumes[@]}"; do
    if podman volume exists "$vol"; then
        podman volume rm "$vol"
    else
        echo "Volume $vol not found, skipping (check 'podman volume ls')."
    fi
done

set_val CMK_SITE_ID "$new_site"

podman compose up -d

echo "Waiting for the new site to answer on http://localhost:8080/$new_site/ ..."
for _ in $(seq 1 60); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:8080/$new_site/check_mk/" || true)"
    if [ "$code" = "302" ] || [ "$code" = "200" ]; then
        break
    fi
    sleep 5
done
echo "Checkmk HTTP status: ${code:-none} (expect 302)"
echo "LIVESTATUS_TCP_TLS: $(podman compose exec checkmk omd config "$new_site" show LIVESTATUS_TCP_TLS 2>/dev/null || echo '?') (expect off)"

cat <<NEXT

Site: $new_site

Next:
  1. On every previously onboarded Linux host, run: cmk-agent-ctl delete-all
  2. Run the wizard: deploy/run-wizard.sh
  3. Hard-refresh the dashboard (Ctrl+Shift+R).
NEXT
