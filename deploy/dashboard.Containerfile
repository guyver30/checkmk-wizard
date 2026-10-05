# React dashboard image (cutover from the vanilla dashboard/, 2026-09-28).
#
# Built by `podman compose build dashboard` with the repo root as build context
# (see the `dashboard` service in compose.yaml). Stage 1 builds the design system
# and the SPA, following dashboard-react/README.md §2; stage 2 serves the static
# result with nginx, so no Node process runs in the deployed stack.
#
# The image contains no per-machine settings: the Checkmk site name and the
# read-only broker credentials come from deploy/.env via /config.json at
# container start (amended 2026-09-30, quick 260930-ixs), same as
# TOPOLOGY_EDITOR_SECRET below. Rebuild after every `git pull`.
#
# Amended 2026-09-30 (quick 260930-hpy): config.ts no longer carries
# TOPOLOGY_EDITOR_SECRET -- the credential comes from deploy/.env at container
# start, via the nginx template below (${TOPOLOGY_EDITOR_SECRET}), never baked
# into this image.

FROM docker.io/library/node:22-alpine AS build
WORKDIR /src

COPY design-system/ design-system/
# `npm pack` ignores --prefix and always packs the current directory, hence the cd.
RUN cd design-system && npm ci && npm run build && npm pack

COPY dashboard-react/ dashboard-react/
RUN npm --prefix dashboard-react ci \
 && npm --prefix dashboard-react run build

FROM docker.io/library/nginx:alpine
# Installed as a template, not a static conf.d file: deploy/dashboard-nginx.conf
# references ${CH_READER_PASSWORD}, ${NGINX_LOCAL_RESOLVERS} and
# ${TOPOLOGY_EDITOR_SECRET}, which the official nginx image's own entrypoint
# renders via envsubst at container start (verified
# 2026-09-30 against github.com/nginxinc/docker-nginx
# entrypoint/20-envsubst-on-templates.sh). This only substitutes variables actually
# present in the container's environment, so nginx's own $uri/$arg_*/$is_args/$args
# variables pass through untouched — they are never environment variables.
COPY deploy/dashboard-nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /src/dashboard-react/dist /usr/share/nginx/html

# Topology map drawing (quick 261005-eln): the nginx worker (uid 101, `nginx`) must be
# able to write /var/lib/map-drawing, where compose mounts the map_drawing_data volume.
# The directory is created here with that owner (a fresh named volume is copied up from
# it), and the entrypoint script below re-asserts ownership on every start so a volume
# created earlier or by another owner is fixed too. Rootless podman maps uid 101 to a
# subuid on the host; the in-container owner is what matters.
RUN install -d -o nginx -g nginx -m 0755 /var/lib/map-drawing
COPY --chmod=0755 deploy/dashboard-entrypoint/30-map-drawing-perms.sh /docker-entrypoint.d/30-map-drawing-perms.sh
