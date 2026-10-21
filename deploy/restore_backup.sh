#!/usr/bin/env bash
# Restore a bundle made by deploy/backup.sh onto this machine: put back
# deploy/.env, the Checkmk site and the topology map drawing, then start the
# stack. Meant for a fresh checkout (docs/DEPLOY-NEW-MACHINE.md §1-§2) but also
# works on an existing stack, replacing its site and drawing.
#
# Usage: deploy/restore_backup.sh BUNDLE.tar [--public-host HOST] [--yes]
#   --public-host HOST  set CMK_PUBLIC_HOST in the restored .env (the address
#                       agents register against; usually differs on a new
#                       machine). Without it the backed-up value is kept.
#   --yes               do not ask before replacing the existing site/volumes
#
# What happens, depending on the bundle's mode:
#   full       the checkmk_data volume is replaced by the exported one
#              (history included), then the stack is started.
#   nohistory  the stack is started with a blank site (the entrypoint creates
#              it from CMK_SITE_ID), the site is stopped, the archive is
#              restored into it with `omd restore --reuse`, then the stack is
#              brought down and up once more.
# Do not run the wizard afterwards: the site already has its configuration.
#
# Always a full down/up: restarting a single container once cut Checkmk off
# from the LAN (docs/DEPLOY-NEW-MACHINE.md §12.3).

set -euo pipefail

bundle=""
public_host=""
assume_yes=false
while [ $# -gt 0 ]; do
    case "$1" in
        --public-host)
            if [ $# -lt 2 ]; then echo "--public-host needs a HOST (see --help)" >&2; exit 2; fi
            public_host="$2"; shift ;;
        --yes) assume_yes=true ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
        *) bundle="$1" ;;
    esac
    shift
done
if [ -z "$bundle" ] || [ ! -f "$bundle" ]; then
    echo "Usage: restore_backup.sh BUNDLE.tar [--public-host HOST] [--yes]" >&2
    exit 2
fi
bundle="$(cd "$(dirname "$bundle")" && pwd)/$(basename "$bundle")"

cd "$(dirname "${BASH_SOURCE[0]}")"
project="${COMPOSE_PROJECT_NAME:-$(basename "$PWD")}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
umask 077
tar -C "$work" -xf "$bundle"
for f in manifest.txt env map_drawing_data.tar; do
    [ -f "$work/$f" ] || { echo "Not a backup bundle: $f missing." >&2; exit 1; }
done
mode="$(sed -n 's/^mode=//p' "$work/manifest.txt")"
site="$(sed -n 's/^site=//p' "$work/manifest.txt")"
case "$mode" in
    full)      [ -f "$work/checkmk_data.tar" ] || { echo "Bundle has no checkmk_data.tar." >&2; exit 1; } ;;
    nohistory) [ -f "$work/site.omd.tar" ]     || { echo "Bundle has no site.omd.tar." >&2; exit 1; } ;;
    *) echo "Unknown bundle mode '$mode'." >&2; exit 1 ;;
esac

echo "Bundle: $(basename "$bundle")  (mode: $mode, site: $site)"
echo "Image at backup time: $(sed -n 's/^checkmk_image=//p' "$work/manifest.txt")"
echo "The checkmk image tag on this machine must be the same (or newer) version."
if ! $assume_yes; then
    read -r -p "Replace the Checkmk site and map drawing of project '$project' on this machine? [y/N] " ans
    [ "$ans" = y ] || [ "$ans" = Y ] || { echo "Aborted; nothing changed."; exit 1; }
fi

# .env: keep the current one as a dated copy, then install the backed-up one.
if [ -f .env ]; then
    cp -p .env ".env.bak-$(date +%Y%m%d-%H%M%S)"
fi
cp "$work/env" .env
chmod 600 .env
if [ -n "$public_host" ]; then
    if grep -q '^CMK_PUBLIC_HOST=' .env; then
        sed -i "s|^CMK_PUBLIC_HOST=.*|CMK_PUBLIC_HOST=$public_host|" .env
    else
        echo "CMK_PUBLIC_HOST=$public_host" >> .env
    fi
fi

echo "Stopping the stack (full down)..."
podman compose down

# Recreate a volume with the labels compose puts on its own, so compose does
# not warn that the volume was not created by it.
fresh_volume() {
    local name="$1"
    podman volume rm -f "${project}_${name}" >/dev/null 2>&1 || true
    podman volume create \
        --label "com.docker.compose.project=$project" \
        --label "com.docker.compose.volume=$name" \
        "${project}_${name}" >/dev/null
}

fresh_volume map_drawing_data
podman volume import "${project}_map_drawing_data" "$work/map_drawing_data.tar"

fresh_volume checkmk_data
if [ "$mode" = full ]; then
    # 2026-10-21: not `podman volume import`. It rejects the site's own
    # symlink (<site>/version -> ../../versions/<ver>.cre, which points
    # outside the volume) with 'Error: invalid symlink', leaving a half-filled
    # volume. Extracting with tar inside the checkmk image keeps the symlinks,
    # owners and modes as exported (by root, so the numeric ids are restored).
    cmk_image="$(sed -n 's|^ *image: *\(checkmk/[^ ]*\).*|\1|p' compose.yaml | head -1)"
    podman run --rm --user root --entrypoint tar \
        -v "${project}_checkmk_data:/data" \
        -v "$work/checkmk_data.tar:/in/checkmk_data.tar:ro,z" \
        "$cmk_image" -xpf /in/checkmk_data.tar -C /data --numeric-owner
    echo "Starting the stack..."
    podman compose up -d
else
    echo "Starting the stack with a blank site, then restoring the archive into it..."
    podman compose up -d
    for _ in $(seq 1 36); do
        podman exec checkmk omd status "$site" >/dev/null 2>&1 && break
        sleep 5
    done
    podman exec checkmk omd status "$site" >/dev/null 2>&1 || {
        echo "Site '$site' did not come up within 3 minutes; check 'podman logs checkmk'." >&2
        exit 1
    }
    podman exec checkmk omd stop "$site"
    podman exec -i checkmk omd restore --reuse "$site" - < "$work/site.omd.tar"
    echo "Restarting the whole stack..."
    podman compose down
    podman compose up -d
fi

echo
echo "Restored. Check the Checkmk UI (http://<this machine>:8080/$site/) and the dashboard (:8090)."
echo "Agents registered against the old CMK_PUBLIC_HOST need re-registering if the address changed."
