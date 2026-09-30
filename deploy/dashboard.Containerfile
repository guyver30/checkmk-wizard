# React dashboard image (cutover from the vanilla dashboard/, 2026-09-28).
#
# Built by `podman compose build dashboard` with the repo root as build context
# (see the `dashboard` service in compose.yaml). Stage 1 builds the design system
# and the SPA, following dashboard-react/README.md §2; stage 2 serves the static
# result with nginx, so no Node process runs in the deployed stack.
#
# The build copies the working tree, so a locally edited
# dashboard-react/src/lib/config.ts (CHECKMK_BASE_URL) is baked into the image.
# Rebuild after editing it or after every `git pull`.
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
