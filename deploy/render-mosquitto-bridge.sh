#!/bin/sh
# Render the Mosquitto cloud bridge fragment for this deployment.
#
# Usage: render-mosquitto-bridge.sh TEMPLATE OUTPUT
#
# Env: CLOUD_BROKER_HOST (empty => bridge disabled, OUTPUT removed),
#      CLOUD_BROKER_PORT (default 8883), CLOUD_BROKER_PASSWORD,
#      CLOUD_BROKER_CAFILE (default /mosquitto/certs/cloud-ca.pem),
#      SITE_SEN, CMK_SITE_ID, MQTT_BRIDGE_PASSWORD.
#
# Every value becomes broker config, so each is validated BEFORE it reaches
# sed. A malformed SEN would otherwise silently land in a topic the archive
# drops. Any failure exits 1 without creating OUTPUT; messages name the
# variable and never echo a password value. chown/chmod of OUTPUT stay in
# compose.yaml (container-only).
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: $0 TEMPLATE OUTPUT" >&2
  exit 2
fi
template=$1
output=$2

host=${CLOUD_BROKER_HOST-}
if [ -z "$host" ]; then
  rm -f "$output"
  echo "render-mosquitto-bridge: CLOUD_BROKER_HOST unset; cloud bridge disabled" >&2
  exit 0
fi

sen=${SITE_SEN-}
site=${CMK_SITE_ID-}
port=${CLOUD_BROKER_PORT:-8883}
cloud_pw=${CLOUD_BROKER_PASSWORD-}
bridge_pw=${MQTT_BRIDGE_PASSWORD-}
cafile=${CLOUD_BROKER_CAFILE:-/mosquitto/certs/cloud-ca.pem}

# check NAME VALUE REGEX: exit 1 unless VALUE is a single line fully matching REGEX.
check() {
  name=$1
  value=$2
  regex=$3
  case $value in
    *'
'*)
      echo "render-mosquitto-bridge: $name contains a newline" >&2
      exit 1
      ;;
  esac
  if ! printf '%s\n' "$value" | grep -Eqx "$regex"; then
    echo "render-mosquitto-bridge: $name is missing or has an invalid format" >&2
    exit 1
  fi
}

check SITE_SEN "$sen" '[1-9][0-9]{0,17}'
check CMK_SITE_ID "$site" '[A-Za-z][A-Za-z0-9_]{0,15}'
check CLOUD_BROKER_HOST "$host" '[A-Za-z0-9][A-Za-z0-9.-]{0,252}'
check CLOUD_BROKER_PORT "$port" '[0-9]{1,5}'
if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
  echo "render-mosquitto-bridge: CLOUD_BROKER_PORT must be 1-65535" >&2
  exit 1
fi
check CLOUD_BROKER_PASSWORD "$cloud_pw" '[A-Za-z0-9_.~=+-]{1,256}'
check MQTT_BRIDGE_PASSWORD "$bridge_pw" '[A-Za-z0-9_.~=+-]{1,256}'
check CLOUD_BROKER_CAFILE "$cafile" '/[A-Za-z0-9_./-]+'
if [ ! -r "$cafile" ]; then
  echo "render-mosquitto-bridge: CLOUD_BROKER_CAFILE is not a readable file" >&2
  exit 1
fi

umask 077
tmp="$output.tmp.$$"
sed \
  -e "s|@SITE_SEN@|$sen|g" \
  -e "s|@SITE_ID@|$site|g" \
  -e "s|@CLOUD_BROKER_HOST@|$host|g" \
  -e "s|@CLOUD_BROKER_PORT@|$port|g" \
  -e "s|@CLOUD_BROKER_PASSWORD@|$cloud_pw|g" \
  -e "s|@CLOUD_BROKER_CAFILE@|$cafile|g" \
  -e "s|@MQTT_BRIDGE_PASSWORD@|$bridge_pw|g" \
  "$template" > "$tmp"
if grep -q '@[A-Z_]*@' "$tmp"; then
  rm -f "$tmp"
  echo "render-mosquitto-bridge: placeholder remained after rendering" >&2
  exit 1
fi
mv "$tmp" "$output"
