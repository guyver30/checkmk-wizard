# React dashboard image (cutover from the vanilla dashboard/, 2026-09-28).
#
# Built by `podman compose build dashboard` with the repo root as build context
# (see the `dashboard` service in compose.yaml). Stage 1 builds the design system
# and the SPA, following dashboard-react/README.md §2; stage 2 serves the static
# result with nginx, so no Node process runs in the deployed stack.
#
# The build copies the working tree, so a locally edited
# dashboard-react/src/lib/config.ts (CHECKMK_BASE_URL, TOPOLOGY_EDITOR_SECRET) is
# baked into the image. Rebuild after editing it or after every `git pull`.

FROM docker.io/library/node:22-alpine AS build
WORKDIR /src

COPY design-system/ design-system/
# `npm pack` ignores --prefix and always packs the current directory, hence the cd.
RUN cd design-system && npm ci && npm run build && npm pack

COPY dashboard-react/ dashboard-react/
RUN npm --prefix dashboard-react ci \
 && npm --prefix dashboard-react run build

FROM docker.io/library/nginx:alpine
COPY deploy/dashboard-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dashboard-react/dist /usr/share/nginx/html
