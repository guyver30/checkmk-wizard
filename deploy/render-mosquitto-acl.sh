#!/bin/sh
# Render the Mosquitto ACL template for this deployment's site.
#
# Usage: render-mosquitto-acl.sh TEMPLATE OUTPUT
#
# Replaces @SITE_ID@ in TEMPLATE with $CMK_SITE_ID and writes OUTPUT. The site
# id becomes broker security config, so it is validated BEFORE it reaches sed:
# charset first (rejects / + # ; $, whitespace, newline), then the shape used
# everywhere else (letter first, at most 16 chars). Any failure exits 1 without
# creating OUTPUT, which aborts the container start under `set -eu`.
# chown/chmod of OUTPUT stay in compose.yaml (container-only).
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: $0 TEMPLATE OUTPUT" >&2
  exit 2
fi
template=$1
output=$2
site=${CMK_SITE_ID-}

if [ -z "$site" ]; then
  echo "render-mosquitto-acl: CMK_SITE_ID is empty or unset" >&2
  exit 1
fi
case $site in
  *[!A-Za-z0-9_]*)
    echo "render-mosquitto-acl: CMK_SITE_ID contains characters outside [A-Za-z0-9_]" >&2
    exit 1
    ;;
esac
if ! printf '%s\n' "$site" | grep -Eqx '[A-Za-z][A-Za-z0-9_]{0,15}'; then
  echo "render-mosquitto-acl: CMK_SITE_ID must start with a letter and be at most 16 characters" >&2
  exit 1
fi

umask 077
tmp="$output.tmp.$$"
sed "s/@SITE_ID@/$site/g" "$template" > "$tmp"
if grep -q '@SITE_ID@' "$tmp"; then
  rm -f "$tmp"
  echo "render-mosquitto-acl: placeholder remained after rendering" >&2
  exit 1
fi
mv "$tmp" "$output"
