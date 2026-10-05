#!/bin/sh
# Runs as root from the official nginx image's /docker-entrypoint.sh, before nginx
# starts. Makes the map drawing volume writable by the nginx worker (user nginx,
# uid 101) on every start, for fresh and pre-existing volumes alike. Not recursive:
# it never touches the drawing file itself.
set -eu
mkdir -p /var/lib/map-drawing
chown nginx:nginx /var/lib/map-drawing
chmod 0755 /var/lib/map-drawing
