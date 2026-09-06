#!/usr/bin/env bash
# Regenerates deploy/mosquitto.passwd from scratch via the real mosquitto_passwd
# binary (argon2id by default) — never hand-roll password hashes.
#
# These are disposable dev/local defaults matching this project's existing
# cmkadmin/cmkadmin and minioadmin/minioadmin convention (D-09). Rotate the
# WS_PASSWORD/POLLER_PASSWORD environment variables before exposing this
# broker beyond a trusted LAN; re-running this script is the supported
# rotation path.
#
# Source: mosquitto_passwd(1) man page (mosquitto.org/man/mosquitto_passwd-1.html).

set -euo pipefail

WS_USER="${WS_USER:-wsreader}"
WS_PASSWORD="${WS_PASSWORD:-wsreader}"
POLLER_USER="${POLLER_USER:-poller}"
POLLER_PASSWORD="${POLLER_PASSWORD:-poller}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASSWD_FILE="$SCRIPT_DIR/mosquitto.passwd"

if command -v podman >/dev/null 2>&1; then
  RUNTIME="podman"
elif command -v docker >/dev/null 2>&1; then
  RUNTIME="docker"
elif command -v mosquitto_passwd >/dev/null 2>&1; then
  RUNTIME="host"
else
  echo "ERROR: no way to run mosquitto_passwd — none of podman, docker, or a host-installed mosquitto_passwd binary were found on PATH." >&2
  echo "Install one of: podman, docker, or the mosquitto-clients package (provides mosquitto_passwd)." >&2
  exit 1
fi

# Path to the password file as seen by mosquitto_passwd itself: the
# container-side mount point for podman/docker, or the real host path
# when running against a host-installed mosquitto_passwd binary.
case "$RUNTIME" in
  podman|docker) PASSWD_PATH="/passwd/mosquitto.passwd" ;;
  host) PASSWD_PATH="$PASSWD_FILE" ;;
esac

# Runtime command prefix ($0-derived SCRIPT_DIR, not $(pwd), so this script
# works from any cwd), so the generation sequence below only has to state
# each mosquitto_passwd invocation once.
case "$RUNTIME" in
  podman)
    # --user 0:0: under rootless Podman, container UID 0 maps to the
    # invoking host user, so the generated file lands owned by that user.
    # Without this flag the file is created as a subuid and the host user
    # cannot chmod, edit, or commit it.
    RUNTIME_PREFIX=(podman run --rm --user 0:0 -v "$SCRIPT_DIR:/passwd:z" eclipse-mosquitto:2)
    ;;
  docker)
    # Docker's UID 0 is real host root, so map to the invoking host user
    # instead so the generated file is owned by them, not root.
    RUNTIME_PREFIX=(docker run --rm --user "$(id -u):$(id -g)" -v "$SCRIPT_DIR:/passwd:z" eclipse-mosquitto:2)
    ;;
  host)
    RUNTIME_PREFIX=()
    ;;
esac

# -c creates/overwrites and MUST appear only on the first invocation —
# including it on the second wipes the first user.
"${RUNTIME_PREFIX[@]}" mosquitto_passwd -b -c "$PASSWD_PATH" "$WS_USER" "$WS_PASSWORD"
"${RUNTIME_PREFIX[@]}" mosquitto_passwd -b "$PASSWD_PATH" "$POLLER_USER" "$POLLER_PASSWORD"

# The broker runs as non-root UID/GID 1883 and must be able to read this
# bind-mounted file (see deploy/mosquitto.conf's password_file directive).
chmod 644 "$PASSWD_FILE"

LINE_COUNT="$(wc -l < "$PASSWD_FILE")"
if [ "$LINE_COUNT" != "2" ]; then
  echo "ERROR: expected 2 lines in $PASSWD_FILE, found $LINE_COUNT" >&2
  exit 1
fi
if ! grep -q "^${WS_USER}:\$" "$PASSWD_FILE"; then
  echo "ERROR: $PASSWD_FILE missing expected hashed entry for '$WS_USER'" >&2
  exit 1
fi
if ! grep -q "^${POLLER_USER}:\$" "$PASSWD_FILE"; then
  echo "ERROR: $PASSWD_FILE missing expected hashed entry for '$POLLER_USER'" >&2
  exit 1
fi

echo "Generated $PASSWD_FILE with hashed entries for '$WS_USER' and '$POLLER_USER'."
