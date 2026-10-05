---
phase: quick-261005-eln
plan: 01
subsystem: dashboard
tags: [topology-map, drawing-layer, nginx-dav, vis-network, zustand]
requires: []
provides:
  - "shared topology map drawing (rectangle, ellipse, line, text) edited in topology edit mode"
  - "nginx location = /map-drawing.json (GET/PUT, json only, 256 KB) on the new map_drawing_data volume"
affects: [dashboard-react, deploy]
key-files:
  created:
    - deploy/dashboard-entrypoint/30-map-drawing-perms.sh
    - dashboard-react/src/lib/mapDrawing.ts
    - dashboard-react/src/lib/mapDrawingClient.ts
    - dashboard-react/src/store/mapDrawingStore.ts
    - dashboard-react/src/components/MapDrawingToolbar.tsx
  modified:
    - deploy/dashboard-nginx.conf
    - deploy/dashboard.Containerfile
    - deploy/compose.yaml
    - deploy/reset-site.sh
    - CLAUDE.md
    - .planning/PROJECT.md
    - dashboard-react/src/components/TopologyMap.tsx
    - dashboard-react/src/routes/IndexRoute.tsx
    - dashboard-react/src/test/fakeVisNetwork.ts
    - dashboard-react/README.md
    - docs/DEPLOY-NEW-MACHINE.md
    - "docs/Podman setup for checkmk, minio, mosquitto, worker.md"
metrics:
  completed: 2026-10-05
---

# Quick 261005-eln: Topology map drawing layer Summary

Shapes and text drawn in vis-network's `beforeDrawing` hook behind the hosts, edited with Select/Rectangle/Ellipse/Line/Text tools in edit mode, and persisted as one shared JSON file through a single nginx WebDAV-PUT location on a new `map_drawing_data` volume. No custom backend.

## Commits

- 5aa0c95: nginx location, volume, ownership script, constraint amendment, deploy docs
- 924350e: drawing model, sanitiser, client and store (with tests)
- Task 3 commit (map integration, toolbar, README): see `git log` on the branch

## What was built

- **nginx** (`deploy/dashboard-nginx.conf`): a `map` on `$request_method:$content_type` (json PUT -> 0, any other PUT -> 1) and an exact-match `location = /map-drawing.json` with `limit_except GET PUT`, `dav_methods PUT`, `create_full_put_path off`, `client_max_body_size 256k`, `client_body_temp_path` on the same volume, `Cache-Control: no-store`, and `return 415` for non-json PUT.
- **Volume and ownership**: `map_drawing_data:/var/lib/map-drawing:z` on the dashboard service only; image directory created with owner `nginx`, plus `/docker-entrypoint.d/30-map-drawing-perms.sh` re-asserting ownership on every start. `reset-site.sh` behaviour unchanged (comment only).
- **Constraint amendment** (2026-10-05) added to CLAUDE.md and .planning/PROJECT.md; deploy docs mention the volume, backup, reset behaviour and the rebuild plus full down/up.
- **Client**: `mapDrawing.ts` (model, palette, `sanitizeDrawing`, hit-testing, move/resize with 25 px snap, canvas renderer), `mapDrawingClient.ts` (GET with 404 as empty, PUT with a 200 KB guard before `fetch`), `mapDrawingStore.ts` (draft/saved/dirty, never persisted).
- **Map**: shapes painted after the grid in `beforeDrawing`; capture-phase `pointerdown` on the canvas host that only engages in edit mode with a drawing tool active and `getNodeAt` reporting no node; toolbar (`MapDrawingToolbar`), load-error status, `beforeunload` guard while dirty, Delete/Backspace key, `onActivity` wired to IndexRoute's idle timer.

## Verification actually run

- Task 1 gate: `sh -n` on the new script, `bash -n deploy/reset-site.sh`, YAML parse of compose.yaml (volume declared, mounted only into `dashboard`), greps for the nginx directives, amendments and docs, and no non-comment `map_drawing` reference in reset-site.sh. All passed.
- `npx vitest run` (full suite): 60 files, 827 tests, all passed (new: 28 mapDrawing, 9 client, 7 store, 16 map integration, 4 toolbar).
- `npm run typecheck`: clean. `npm run lint`: exit 0; only pre-existing warnings, none in new files. `npm run build`: succeeded.
- Existing TopologyMap, IndexRoute and App suites pass unmodified; the new mount-time load does a real relative `fetch` in them, fails inside jsdom and is shown as the non-blocking message, so no mock was needed.

## NOT verified (be explicit)

- nginx was never run: no nginx, podman or docker on this machine. `nginx -t` on the new config was not run, so the `map` regex quoting, `limit_except` plus `dav_methods` inside an exact-match location and the `if` / `return 415` are unchecked.
- `ngx_http_dav_module` presence in `docker.io/library/nginx:alpine` is from reading pkg-oss `alpine/Makefile` (checked 2026-10-05, per planning), not from running the image.
- The Containerfile `RUN install -d`, `COPY --chmod`, entrypoint script and the `:z` volume ownership under rootless podman were not built or run.
- No browser test: pointer behaviour (capture-phase interception against real vis-network/hammer.js, panning, node drag precedence) was tested only against the FakeNetwork in jsdom.
- `getNodeAt` is part of vis-network's public API but its behaviour on real canvases was not exercised here.

Deploy-host checks to run:

1. `podman run --rm docker.io/library/nginx:alpine nginx -V 2>&1 | tr ' ' '\n' | grep dav`
2. `podman compose build dashboard`, then `podman compose down && podman compose up -d`
3. `curl -i http://localhost:8090/map-drawing.json` (404 before first save)
4. `curl -i -X PUT -H 'Content-Type: application/json' --data '{"version":1,"updated_at":null,"shapes":[]}' http://localhost:8090/map-drawing.json` (201/204)
5. `curl -i -X PUT -H 'Content-Type: text/plain' --data x http://localhost:8090/map-drawing.json` (415)
6. `curl -i -X DELETE http://localhost:8090/map-drawing.json` (403)
7. `curl -i -X PUT --data x http://localhost:8090/other.json` (405)
8. In a browser: edit mode, draw, Save, reload; confirm host drag and snap still work with the Hosts tool and that a press on a host under a shape drags the host.

## Deviations from Plan

### Auto-fixed / judgement calls

**1. [Rule 3 - Base] Worktree base reset.** The worktree started on 41fffac, not the required 68fc9f5; reset to 68fc9f5 as instructed (HEAD was a per-agent branch, so safe). Nothing lost.

**2. [Rule 2 - Hardening] Shape id length cap.** The plan did not cap shape id length; an untrusted file could carry huge ids. Added `MAX_ID_LENGTH = 64` to `sanitizeDrawing` (ids longer are dropped) and de-duplicated ids on load. Without a cap, a sanitised drawing could never reach the 200 KB client guard and the oversize test needed ids longer than 64 bytes passed straight to `saveDrawing`.

**3. Select tool on empty canvas.** The plan said "clear the selection and let nothing else happen". Implemented as: clear the selection and do not stop the event, so vis-network can still pan the map. Taking the press would have made panning impossible while the Select tool is active. Easy to flip if the stricter reading was intended.

**4. TDD ordering.** For the Task 2 lib tests I wrote the test file first and then the implementation, but did not capture a separate failing (RED) run or separate test/feat commits; Task 2 and Task 3 each landed as one commit.

**5. Delete/Backspace key** is handled by a window listener in TopologyMap (active only in edit mode, ignoring input/textarea/select/contenteditable) rather than on the map container, because the canvas host is not focusable.

**6. Hosts tool label.** The tool toggle for "no drawing tool" is labelled "Hosts" (accessible name) with a title explaining it.

## Assumption Drift (advisory)

- Found during Task 3: the plan said `getNodeAt` is added to the fake "if not already present"; FakeNetwork had neither `getNodeAt` nor `redraw` (existing `redraw()` calls in TopologyMap only worked because the network ref was still null on first effect run). Both were added; no existing behaviour changed.

## Known Stubs

None.

## Threat Flags

None beyond the plan's register: the new open PUT surface is T-eln-01 (accepted) and is limited as T-eln-02, 03, 06 describe, but see "NOT verified" for nginx enforcement.

## Self-Check: PASSED

Files verified present and commits 5aa0c95 and 924350e exist; the Task 3 commit is on the branch (see git log).
