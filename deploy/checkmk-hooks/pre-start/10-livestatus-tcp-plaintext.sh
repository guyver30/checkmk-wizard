#!/bin/bash
# Turn LIVESTATUS_TCP_TLS off before the Checkmk site starts.
#
# Bug fixed 2026-09-25: a fresh Checkmk 2.4.0 site defaults to
# LIVESTATUS_TCP_TLS=on, so xinetd forwards port 6557 to `tmp/run/live-tcp`,
# which symlinks to `live-tls`. Plain LQL clients (the wizard's livestatus.py
# and scripts/mqtt_poller.py) then get "Connection reset by peer" / "Malformed
# columns response" and the dashboard shows "connected" but stays empty.
# CMK_LIVESTATUS_TCP=on only runs `omd config set LIVESTATUS_TCP on`.
#
# Why a hook: docs.checkmk.com/latest/en/introduction_docker.html lists no
# environment variable for LIVESTATUS_TCP_TLS. The hook mechanism itself is
# verified from the image's entrypoint source (github.com/Checkmk/checkmk,
# branch 2.4.0, docker_image/docker-entrypoint.sh): `exec_hook pre-start` runs
# every executable file in /docker-entrypoint.d/pre-start/ as root, on every
# container start, with the site still stopped (so `omd config set` is
# allowed), immediately before `omd start`. The file must be executable.
#
# Always exits 0 and does not use `set -e`: whether the entrypoint runs under
# `set -e` is unverified, and a failed hook must never stop Checkmk starting.

site="${CMK_SITE_ID:-cmk}"

tls="$(omd config "$site" show LIVESTATUS_TCP_TLS 2>/dev/null)"

if [ "$tls" = "on" ]; then
    echo "Livestatus TCP TLS is on for site '$site'; turning it off for plain-text LQL clients"
    if ! omd config "$site" set LIVESTATUS_TCP_TLS off; then
        echo "WARNING: could not set LIVESTATUS_TCP_TLS off for site '$site'"
    fi
fi

exit 0
