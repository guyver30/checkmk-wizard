#!/usr/bin/env bash
# Run checkmk-wizard inside the automation-worker container (container mode).
#
# Checks first that the worker is running and that it received
# CMK_REST_SECRET from deploy/.env: .env is read only when compose creates the
# container, so a value added later needs a full down/up before the wizard can
# provision the `automation` user with it (docs/WIZARD-OPERATION.md,
# "Troubleshooting: the wizard asks for Automation secret").
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

echo "At the cmkadmin prompt, enter the password (the compose default 'cmkadmin' on a new site)."
echo "Leaving it blank skips creating the 'automation' user from CMK_REST_SECRET."
echo

exec podman exec --interactive --tty "$container" \
    bash -c "cd /app/checkmk-wizard && uv sync && uv run checkmk-wizard"
