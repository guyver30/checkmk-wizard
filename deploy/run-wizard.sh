#!/usr/bin/env bash
# Run checkmk-wizard inside the automation-worker container (container mode).
#
# Checks first that the worker is running and received CMK_REST_SECRET from
# deploy/.env, then waits until the Checkmk site answers. .env is read only when
# compose creates the container, so a value added later needs a full down/up
# before the wizard can provision the `automation` user with it
# (docs/WIZARD-OPERATION.md, "Troubleshooting: the wizard asks for Automation
# secret").
#
# `uv sync` runs every time because the checkout is bind-mounted: a git pull on
# the host updates the code the container runs, but not its virtualenv.
#
# Usage: deploy/run-wizard.sh

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
container=automation-worker

if [ "$(podman inspect -f '{{.State.Running}}' "$container" 2>/dev/null)" != "true" ]; then
    echo "$container is not running. Start the stack first: (cd deploy && podman compose up -d)" >&2
    exit 1
fi

secret_len="$(podman exec "$container" bash -c 'echo ${#CMK_REST_SECRET}')"
if [ "$secret_len" = "0" ]; then
    cat >&2 <<EOF
CMK_REST_SECRET is empty inside $container.
Set it in deploy/.env (e.g. openssl rand -base64 24), then recreate the stack:
  cd deploy && podman compose down && podman compose up -d
EOF
    exit 1
fi

# Wait until the site answers from inside the worker, over the same
# checkmk:5000 path the wizard uses. Added 2026-09-30 after a live run started
# while the checkmk container was still creating a new site: the wizard then
# failed its GUI login with "All connection attempts failed". Status meanings
# (container apache in front of the site apache): no response or 502/503 =
# still starting; 404 = no site with that name in the checkmk_data volume.
site="$(podman exec "$container" printenv CMK_SITE_ID 2>/dev/null || echo dmc)"
probe='import sys, urllib.error, urllib.request
try:
    print(urllib.request.urlopen(sys.argv[1], timeout=5).status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception:
    print(0)'
url="http://checkmk:5000/$site/check_mk/login.py"
echo "Waiting for Checkmk site '$site' to answer (up to 3 minutes)..."
code=0
for _ in $(seq 1 36); do
    code="$(podman exec "$container" python3 -c "$probe" "$url")"
    case "$code" in
        200|302) break ;;
        404)
            echo "Checkmk answers, but there is no site '$site' (CMK_SITE_ID in deploy/.env)." >&2
            echo "Sites in the checkmk container:" >&2
            podman exec checkmk omd sites >&2 || true
            echo "Fix CMK_SITE_ID and run: cd deploy && podman compose down && podman compose up -d" >&2
            exit 1
            ;;
    esac
    sleep 5
done
if [ "$code" != "200" ] && [ "$code" != "302" ]; then
    echo "Site '$site' did not answer on $url after 3 minutes (last status: $code)." >&2
    echo "Check: podman logs --tail 30 checkmk" >&2
    exit 1
fi
echo "Site '$site' is up."

echo "At the cmkadmin prompt, enter the password (the compose default 'cmkadmin' on a new site)."
echo "Leaving it blank skips creating the 'automation' user from CMK_REST_SECRET."
echo

exec podman exec --interactive --tty "$container" \
    bash -c "cd /app/checkmk-wizard && uv sync && uv run checkmk-wizard"
