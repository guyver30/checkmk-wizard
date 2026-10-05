---
phase: quick-261005-eln
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - deploy/dashboard-nginx.conf
  - deploy/dashboard.Containerfile
  - deploy/dashboard-entrypoint/30-map-drawing-perms.sh
  - deploy/compose.yaml
  - deploy/reset-site.sh
  - CLAUDE.md
  - .planning/PROJECT.md
  - docs/DEPLOY-NEW-MACHINE.md
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
  - dashboard-react/src/lib/mapDrawing.ts
  - dashboard-react/src/lib/mapDrawing.test.ts
  - dashboard-react/src/lib/mapDrawingClient.ts
  - dashboard-react/src/lib/mapDrawingClient.test.ts
  - dashboard-react/src/store/mapDrawingStore.ts
  - dashboard-react/src/store/mapDrawingStore.test.ts
  - dashboard-react/src/components/MapDrawingToolbar.tsx
  - dashboard-react/src/components/MapDrawingToolbar.test.tsx
  - dashboard-react/src/components/TopologyMap.tsx
  - dashboard-react/src/components/TopologyMapDrawing.test.tsx
  - dashboard-react/src/test/fakeVisNetwork.ts
  - dashboard-react/src/routes/IndexRoute.tsx
  - dashboard-react/README.md
autonomous: true
requirements: [QUICK-261005-ELN]

must_haves:
  truths:
    - "In topology edit mode the operator can pick a drawing tool (select, rectangle, ellipse, line, text), create shapes on empty canvas, select, move, resize (lines: drag endpoints), edit a text label, pick stroke and fill from a small palette, and delete"
    - "Shapes are drawn in vis-network's beforeDrawing hook after the grid, so they sit behind edges and host nodes and pan/zoom with them"
    - "With no drawing tool active (the default, and always outside edit mode) the drawing is inert: node click, node drag, grid snap and map_position writes behave exactly as before"
    - "Even with a drawing tool active, a pointerdown on a host node goes to vis-network (node drag and snap keep working); only empty-canvas and shape hits are taken by the drawing layer"
    - "Outside edit mode the drawing renders read-only, with no drawing toolbar"
    - "On map mount the drawing is loaded with GET /map-drawing.json; 404 means empty drawing; any other failure shows a non-blocking message and the map stays usable"
    - "Edit mode shows Save, Revert and an unsaved-changes indicator; Save PUTs the whole drawing with updated_at (last write wins); Revert restores the last loaded or saved drawing"
    - "Loaded JSON is sanitised: unknown shape types dropped, numbers clamped, text length capped, colours restricted to the palette; text is drawn with ctx.fillText, never as HTML"
    - "nginx accepts GET/HEAD and PUT (application/json only, 256 KB cap) on exactly /map-drawing.json; no other path or method can write to the volume"
    - "The drawing file lives on a new named volume map_drawing_data mounted only into the dashboard container, owned by the nginx worker user, survives podman compose down/up, and is not deleted by reset-site.sh"
  artifacts:
    - path: "dashboard-react/src/lib/mapDrawing.ts"
      provides: "Shape model, palette, sanitizeDrawing, serializeDrawing, hit-testing, move/resize math, drawShapes canvas renderer"
      exports: ["sanitizeDrawing", "serializeDrawing", "emptyDrawing", "hitTest", "moveShape", "resizeShape", "drawShapes", "MAX_DRAWING_BYTES", "DRAWING_PALETTE"]
    - path: "dashboard-react/src/lib/mapDrawingClient.ts"
      provides: "loadDrawing (GET, 404 -> empty) and saveDrawing (PUT, size-capped)"
      exports: ["loadDrawing", "saveDrawing", "MAP_DRAWING_URL"]
    - path: "dashboard-react/src/store/mapDrawingStore.ts"
      provides: "zustand store: saved, draft, dirty, selectedId, tool, loadError, saveError, saving; load/save/revert/add/update/remove/select/setTool"
    - path: "dashboard-react/src/components/MapDrawingToolbar.tsx"
      provides: "Edit-mode-only tools, palette, text input, delete, Save, Revert, unsaved indicator"
    - path: "deploy/dashboard-nginx.conf"
      provides: "location = /map-drawing.json with dav_methods PUT"
      contains: "dav_methods PUT"
    - path: "deploy/compose.yaml"
      provides: "map_drawing_data named volume mounted into dashboard only"
      contains: "map_drawing_data"
  key_links:
    - from: "dashboard-react/src/components/TopologyMap.tsx"
      to: "drawShapes in src/lib/mapDrawing.ts"
      via: "network.on(\"beforeDrawing\") right after drawGrid"
      pattern: "drawShapes\\("
    - from: "dashboard-react/src/lib/mapDrawingClient.ts"
      to: "nginx location = /map-drawing.json"
      via: "fetch GET and PUT with Content-Type application/json"
      pattern: "/map-drawing\\.json"
    - from: "deploy/dashboard-nginx.conf"
      to: "map_drawing_data volume mounted at /var/lib/map-drawing"
      via: "root /var/lib/map-drawing in the exact-match location"
      pattern: "/var/lib/map-drawing"
---

<objective>
Add a minimal drawing layer (rectangle, ellipse, line, text) to the topology map, edited in topology edit mode and drawn behind host nodes in the same vis-network coordinate space, and persist one shared drawing as a JSON file on a new named volume, written by the browser through one narrowly scoped nginx WebDAV-PUT location. No custom backend.

Purpose: groundwork for the location phase (Phase 15). An operator sketches an elevator shaft, floor lines and floor labels, then drags hosts onto them (host positions keep persisting through Checkmk map_position, unchanged). Floors, towers and layers are NOT part of this task.

Output: nginx location, volume and permissions; client model, IO and store with tests; map integration and toolbar with tests; docs and the dated constraint amendment.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md
@deploy/dashboard-nginx.conf
@deploy/dashboard.Containerfile
@dashboard-react/src/components/TopologyMap.tsx
@dashboard-react/src/test/fakeVisNetwork.ts

<planner_findings>
Verified during planning (cite these in code comments and the SUMMARY):

1. Map technology: vis-network 10 on a canvas, not SVG. TopologyMap.tsx already draws the grid in network coordinates from network.on("beforeDrawing", ctx => drawGrid(...)) and tier markers from afterDrawing. vis-network calls beforeDrawing before it draws edges and nodes, so drawing shapes there puts them behind nodes and makes them pan and zoom with the map with no bookkeeping. This is the least invasive integration: no second canvas or SVG overlay to keep in sync with view position and scale, and no overlay that could swallow node pointer events. Interaction is a capture-phase pointerdown handler on the map wrapper that engages only when a drawing tool is active AND network.getNodeAt reports no node under the pointer, so vis-network's node drag, the dragEnd grid snap and the map_position write are untouched.

2. ngx_http_dav_module is available in the stock image. deploy/dashboard.Containerfile uses docker.io/library/nginx:alpine; the official docker-nginx alpine image installs nginx.org's Alpine package built by nginx/pkg-oss, whose alpine/Makefile base configure args contain `--with-http_dav_module` (checked 2026-10-05 against raw.githubusercontent.com/nginx/pkg-oss/master/alpine/Makefile). The worker user is `nginx`, uid 101 (docker-nginx Dockerfile: `adduser -S -D -H -u 101 ... nginx`). NOT verified by running anything: no podman, docker or nginx binary exists on this dev machine (the stack runs on a separate deploy host). The SUMMARY must say so and give the user `podman run --rm docker.io/library/nginx:alpine nginx -V 2>&1 | tr ' ' '\n' | grep dav` as the confirmation to run on the deploy host, and state that `nginx -t` on the new config was not run.

3. Existing pending-changes pattern: Checkmk topology edits are written immediately, the "N changes not yet applied" count survives leaving edit mode (IndexRoute does not reset pendingCount on toggle-off), and the 5-minute idle timeout turns edit mode off without asking. Least surprising equivalent for the drawing: leaving edit mode (by toggle or idle timeout) KEEPS the draft in memory (zustand store, never persisted to browser storage); the map keeps rendering the draft; the unsaved indicator reappears when edit mode is re-entered; a beforeunload prompt guards reload or close while the draft is dirty. No confirm dialog on toggle-off (the idle timeout could not answer one).

4. deploy/dashboard-nginx.conf is an envsubst template: nginx's own $variables are safe because only real environment variable names are substituted. New lines must not use ${...} braces.

5. deploy/reset-site.sh (around line 115) deletes only ${project}_checkmk_data, ${project}_mosquitto_data and, with history, ${project}_clickhouse_data. It must keep not touching the new volume.

6. IndexRoute wraps the map in a div with onPointerDown={touch} (edit idle timer). The drawing layer's capture handler stops propagation for the events it takes, so that bubble handler will not fire for them; TopologyMap gets an optional onActivity prop that IndexRoute wires to touch.
</planner_findings>

<interfaces>
From dashboard-react/src/lib/topologyLayout.ts:
  export const MAP_SNAP_SPACING = GRID_SPACING / 3;   // 50
  export function snapToGrid(value: number): number;

From dashboard-react/src/components/TopologyMap.tsx (current, 851 lines):
  props: topologyDevices, statuses, nowMs, editMode?, onEditSaved?, onEditFailed?, incidentLookup?, tierLookup?, onSelectHost?
  mount effect (deps [hasNodes]) creates new Network(container, {nodes, edges}, NETWORK_OPTIONS) and registers
    network.on("beforeDrawing", ctx => drawGrid(ctx, network, container)) and an afterDrawing tier-marker hook;
  tierLookup changes call networkRef.current?.redraw() (around line 355): reuse this pattern for drawing changes;
  refs-for-callbacks pattern (editModeRef, onEditSavedRef...) because handlers are registered once;
  render: root div (ROOT_CLASS_NAME, relative) with overlays (banner top, edge hint bottom-left, zoom group bottom-right) and <div ref={containerRef} className="h-full w-full bg-white" />.

From dashboard-react/src/test/fakeVisNetwork.ts (globally mocked in vitest.setup.ts for "vis-network/peer"):
  class FakeNetwork { on, once, off, setOptions, destroy, getPositions, DOMtoCanvas (identity), getScale, moveTo, fit, focus, disableEditMode, enableEditMode, emit(event, params) }
  Add: getNodeAt(pos) returning a test-settable `nodeAtResult: string | undefined`, and redraw() with a redrawCount counter if not already present.

From dashboard-react/src/routes/IndexRoute.tsx:
  const { touch } = useEditIdleTimeout(editMode, ...); <TopologyMap ... editMode={editMode} ... />
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: nginx WebDAV-PUT location, named volume with worker-writable ownership, constraint amendment, deploy docs</name>
  <files>deploy/dashboard-nginx.conf, deploy/dashboard.Containerfile, deploy/dashboard-entrypoint/30-map-drawing-perms.sh, deploy/compose.yaml, deploy/reset-site.sh, CLAUDE.md, .planning/PROJECT.md, docs/DEPLOY-NEW-MACHINE.md, docs/Podman setup for checkmk, minio, mosquitto, worker.md</files>
  <action>
nginx (deploy/dashboard-nginx.conf). At file top level BEFORE `server {` (the file is included inside nginx's http context as conf.d/default.conf, so `map` is valid there) add a map keyed on the string "$request_method:$content_type" that sets $map_drawing_bad_type: first entry a case-insensitive regex for PUT with content type application/json, optionally followed by `;` parameters, maps to 0; second entry regex `^PUT:` maps to 1; default 0 (nginx map takes the first matching regex in file order, so the json entry must come first). Inside `server` add an exact-match `location = /map-drawing.json` with: root /var/lib/map-drawing (file becomes /var/lib/map-drawing/map-drawing.json); limit_except GET PUT with deny all (GET implies HEAD; DELETE, MKCOL, COPY, MOVE, POST get 403); dav_methods PUT; create_full_put_path off; dav_access user:rw group:r all:r; client_max_body_size 256k; client_body_temp_path /var/lib/map-drawing/.tmp (same filesystem as the target so the DAV module's final rename is a plain rename; the nginx master creates the directory at startup); default_type application/json; add_header Cache-Control "no-store" always; and an `if ($map_drawing_bad_type)` that only does return 415 (return-only is the safe use of if). Comment block in the file's existing style: why (Phase 15 groundwork, quick 261005-eln); second dashboard write surface after /checkmk-api/; open with no auth on the closed demo network like /admin-config.json and /triage-config.json; exact-match means any other path (traversal attempts are normalised by nginx before matching; /map-drawing.json/ and other filenames) falls to the SPA `/` location, where dav_methods is off and the static module answers PUT with 405; the 256k cap sits above the client's own 200 KB cap; ngx_http_dav_module is compiled into the official nginx:alpine image (pkg-oss alpine/Makefile, checked 2026-10-05, not run locally); nginx does not validate JSON, the client sanitises on load. No ${...} braces in the new lines.

Ownership. Create deploy/dashboard-entrypoint/30-map-drawing-perms.sh (POSIX sh, set -eu, mode 0755): mkdir -p /var/lib/map-drawing, chown nginx:nginx /var/lib/map-drawing, chmod 0755 /var/lib/map-drawing (not recursive; never touches the file). The official image's /docker-entrypoint.sh runs /docker-entrypoint.d/*.sh as root before nginx starts (the same mechanism the existing 20-envsubst-on-templates.sh and 15-local-resolvers.envsh rely on), so this fixes ownership on every start for fresh and pre-existing volumes alike. In deploy/dashboard.Containerfile's final stage add a RUN that does install -d -o nginx -g nginx -m 0755 /var/lib/map-drawing (a fresh named volume is copied up from the image directory with that owner) and a COPY --chmod=0755 of the script to /docker-entrypoint.d/30-map-drawing-perms.sh, with a short comment saying both and why (worker uid 101 must write; rootless podman maps it to a subuid, the in-container owner is what matters).

compose (deploy/compose.yaml). On the dashboard service add a volumes list with map_drawing_data:/var/lib/map-drawing:z (comment: dashboard only; written through nginx's /map-drawing.json location; survives down/up). Add map_drawing_data to the top-level volumes block. Touch no other service.

reset-site.sh: no behaviour change. Add one comment line by the volumes=(...) array: map_drawing_data (the topology map drawing) is deliberately not removed by a site reset.

Constraint amendment: append to the "No new backend for the dashboard" bullet in BOTH CLAUDE.md and .planning/PROJECT.md, same italic-parenthesised style as the existing amendments, this text: *(Amended 2026-10-05, quick 261005-eln: still no custom server-side application; the dashboard's nginx gains a second write surface, `location = /map-drawing.json`, which uses the stock ngx_http_dav_module to accept GET and PUT (application/json only, 256 KB cap) of exactly one file on the new `map_drawing_data` volume, holding the topology map's shared drawing layer (shapes and text, groundwork for Phase 15 locations); there is no auth beyond what the dashboard already has (open on the closed demo network, like `wsadmin`/`wstriage`); the browser validates the file on load; last write wins.)*

Docs. docs/DEPLOY-NEW-MACHINE.md (build/start and "Updating later" sections): the dashboard now has a map_drawing_data volume, created on first up, nothing to configure; deploy/reset-site.sh keeps it; back up with podman volume export deploy_map_drawing_data -o map-drawing-backup.tar (name is prefixed by the compose project, check podman volume ls); clear the drawing by removing that volume while the stack is down; to pick up this change run podman compose build dashboard, then podman compose down && podman compose up -d (full down/up, a single-container restart has cut Checkmk egress before). docs/Podman setup for checkmk, minio, mosquitto, worker.md: in the fresh-site reset section (around "remove the Checkmk volume and the Mosquitto volume") add one sentence that map_drawing_data is not part of a site reset and is kept. Keep edits short and in each file's tone.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && grep -q "dav_methods PUT" deploy/dashboard-nginx.conf && grep -q "location = /map-drawing.json" deploy/dashboard-nginx.conf && grep -q "client_max_body_size 256k" deploy/dashboard-nginx.conf && ! grep -v '^\s*#' deploy/dashboard-nginx.conf | grep -n 'map' | grep -q '\${' && grep -q "map_drawing_data:/var/lib/map-drawing:z" deploy/compose.yaml && grep -q "30-map-drawing-perms.sh" deploy/dashboard.Containerfile && test -x deploy/dashboard-entrypoint/30-map-drawing-perms.sh && sh -n deploy/dashboard-entrypoint/30-map-drawing-perms.sh && bash -n deploy/reset-site.sh && test "$(grep -v '^\s*#' deploy/reset-site.sh | grep -c map_drawing)" = 0 && grep -q "Amended 2026-10-05, quick 261005-eln" CLAUDE.md && grep -q "Amended 2026-10-05, quick 261005-eln" .planning/PROJECT.md && grep -q "map_drawing_data" docs/DEPLOY-NEW-MACHINE.md && uv run --no-project --with pyyaml python -c "import yaml; d=yaml.safe_load(open('deploy/compose.yaml')); assert 'map_drawing_data' in d['volumes']; assert any('map_drawing_data' in v for v in d['services']['dashboard']['volumes']); assert not any('map_drawing_data' in str(s.get('volumes','')) for n,s in d['services'].items() if n!='dashboard')" && echo OK</automated>
  </verify>
  <done>nginx has exactly one new write location (GET/PUT, json-only, 256k, exact path) plus the content-type map; the volume is declared, mounted only into dashboard with :z, and made writable for uid 101 by image dir + entrypoint script; reset-site.sh behaviour unchanged; dated amendment present in CLAUDE.md and PROJECT.md; deploy docs mention the volume, backup, reset behaviour and the build + full down/up instruction.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Drawing model, sanitiser, renderer math, load/save client and store (TDD)</name>
  <files>dashboard-react/src/lib/mapDrawing.ts, dashboard-react/src/lib/mapDrawing.test.ts, dashboard-react/src/lib/mapDrawingClient.ts, dashboard-react/src/lib/mapDrawingClient.test.ts, dashboard-react/src/store/mapDrawingStore.ts, dashboard-react/src/store/mapDrawingStore.test.ts</files>
  <behavior>
    - sanitizeDrawing(non-object, null, array, wrong version) returns an empty drawing; version must be 1
    - shapes with unknown type, missing or non-finite numbers, or non-string id are dropped; at most MAX_SHAPES (500) kept
    - coordinates clamped to plus/minus COORD_LIMIT (100000); rect/ellipse width/height clamped to 1..COORD_LIMIT; strokeWidth clamped to 1..12; fontSize restricted to the allowed set (fallback 16)
    - stroke/fill not in DRAWING_PALETTE fall back to the default stroke / no fill (fill may be null)
    - text is coerced to string, control characters stripped, capped at MAX_TEXT_LENGTH (200); a "<script>" text survives only as literal characters (no special handling needed because rendering never uses HTML)
    - serializeDrawing(shapes, now) returns JSON with version 1, ISO updated_at and the shapes; round-trips through sanitizeDrawing unchanged; byte length helper rejects over MAX_DRAWING_BYTES (200000)
    - hitTest: returns topmost (last) shape under a canvas point with tolerance in canvas units; rect/ellipse inside or on border, line within tolerance of the segment, text inside its approximate box; selected-shape handles (rect/ellipse corners, line endpoints) win over bodies
    - moveShape translates all coordinates; resizeShape moves the dragged corner or endpoint and normalises negative width/height; both snap to SHAPE_SNAP (25, half of MAP_SNAP_SPACING)
    - drawShapes calls ctx.strokeRect/ellipse/lineTo/fillText in array order and uses fillText (never innerHTML) for text; selected shape gets handles drawn
    - loadDrawing: 200 + valid JSON returns sanitised drawing; 404 returns empty drawing; 500, network error, or non-JSON body rejects with a typed error
    - saveDrawing: PUT to /map-drawing.json with Content-Type application/json and the serialised body; non-2xx (including 413/415) rejects; oversize drawing rejects BEFORE fetch is called
    - store: load sets saved and draft (does not overwrite a dirty draft); edits set dirty; revert restores saved and clears dirty and selection; save success sets saved to draft and clears dirty; save failure keeps dirty and sets saveError; load failure sets loadError and leaves an empty drawing
  </behavior>
  <action>
Write the tests first (vitest, vi.stubGlobal("fetch", vi.fn()) for the client and store, restore in afterEach), run them red, then implement.

src/lib/mapDrawing.ts (pure, no DOM access besides the ctx it is given, header comment in the project's why-style naming quick 261005-eln and Phase 15 groundwork). Types: Shape is a discriminated union on `type` of "rect" | "ellipse" (id, x, y, w, h, stroke, fill, strokeWidth), "line" (id, x1, y1, x2, y2, stroke, strokeWidth) and "text" (id, x, y, text, stroke, fontSize); Drawing is { version: 1, updated_at: string | null, shapes: Shape[] }. Constants: DRAWING_VERSION, MAX_SHAPES 500, MAX_TEXT_LENGTH 200, COORD_LIMIT 100000, MAX_DRAWING_BYTES 200000 (kept below nginx's 256k), SHAPE_SNAP 25, FONT_SIZES [12, 16, 24, 36], DRAWING_PALETTE (about six hex colours that read on the white map: dark grey, blue, green, amber, red, purple; fill rendered at low alpha so nodes stay visible), DEFAULT_STROKE. Functions: emptyDrawing, sanitizeDrawing, serializeDrawing, drawingByteLength, newShapeId (crypto.randomUUID when available), hitTest(shapes, point, tolerance, selectedId) returning { id, handle } or null where handle is "body" | "nw" | "ne" | "sw" | "se" | "p1" | "p2", moveShape(shape, dx, dy), resizeShape(shape, handle, point), snapShapeValue, and drawShapes(ctx, shapes, selectedId, scale) using ctx.save/restore, lineWidth divided by scale for handles only, globalAlpha for fills, ctx.font with a fixed system sans-serif family, ctx.fillText for text. Text box size for hit-testing is approximated as text length times 0.6 times fontSize by fontSize (no measureText dependency, deterministic in jsdom). Shape snapping uses 25 rather than the node grid's 50 so floor labels are not too coarse while lines still line up with the node grid.

src/lib/mapDrawingClient.ts: MAP_DRAWING_URL = "/map-drawing.json"; loadDrawing() does fetch with cache "no-store" and Accept application/json; 404 resolves emptyDrawing(); any other non-ok, a fetch rejection, or a JSON parse failure rejects with MapDrawingError (message suitable for UI, e.g. status code). Note in a comment that the Vite dev server has no such location (load shows the non-blocking error or 404 there, save fails) -- acceptable, the feature is exercised against the built image. saveDrawing(shapes) builds the body with serializeDrawing(shapes, new Date()), rejects with MapDrawingError "Drawing is too large to save" if drawingByteLength exceeds MAX_DRAWING_BYTES without calling fetch, otherwise PUT with Content-Type application/json; non-2xx rejects (413 and 415 get specific messages); resolves the saved Drawing.

src/store/mapDrawingStore.ts (zustand, matching existing src/store/*.ts style; never persisted -- same "edit-session state is not persisted" rule as IndexRoute's editMode): state saved (Drawing), draft (Shape[]), dirty, selectedId, tool ("none" | "select" | "rect" | "ellipse" | "line" | "text"), stroke, fill, loading, loadError, saving, saveError. Actions: load() (skips if a load is in flight; if dirty, only updates saved and leaves draft), save(), revert(), addShape, updateShape(id, patch or replacement), removeShape(id), select(id or null), setTool, setStroke and setFill (also apply to the selected shape), clearErrors, and a test-only reset. Edits set dirty true. Keep last-write-wins: no ETag/If-Match, no merge.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard/dashboard-react && npx vitest run src/lib/mapDrawing.test.ts src/lib/mapDrawingClient.test.ts src/store/mapDrawingStore.test.ts</automated>
  </verify>
  <done>All three new test files pass and cover sanitisation (unknown type dropped, clamping, text cap, palette fallback), serialisation round-trip and size cap, hit-testing with handles, move/resize with snap, load 200/404/500/non-JSON, save success/500/oversize-without-fetch, and store dirty/revert/save transitions.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Map integration (behind-nodes render, edit-mode-only tools, pointer handling), toolbar, IndexRoute wiring, README, full checks</name>
  <files>dashboard-react/src/components/TopologyMap.tsx, dashboard-react/src/components/MapDrawingToolbar.tsx, dashboard-react/src/components/MapDrawingToolbar.test.tsx, dashboard-react/src/components/TopologyMapDrawing.test.tsx, dashboard-react/src/test/fakeVisNetwork.ts, dashboard-react/src/routes/IndexRoute.tsx, dashboard-react/README.md</files>
  <behavior>
    - emitting beforeDrawing on the FakeNetwork draws the grid and then the stored shapes (assert on a recording ctx: shape calls happen inside beforeDrawing, after the grid stroke); emitting afterDrawing draws no shapes
    - outside edit mode the drawing toolbar is absent and a pointerdown on a shape does not select it or stop propagation
    - in edit mode the toolbar shows tools, palette, Save and Revert; Save is disabled and no unsaved indicator when clean; after adding a shape the indicator ("Unsaved drawing changes") shows and Save is enabled
    - with the rect tool, pointerdown/move/up on empty canvas (getNodeAt returns undefined) creates a rect in the store; with getNodeAt returning a node id the event is not taken and no shape is created
    - with tool "none" in edit mode, empty-canvas pointerdown is never taken (vis-network keeps panning and node behaviour)
    - Revert restores the saved drawing; Save calls saveDrawing and clears the indicator on success, shows an error message on failure while keeping the draft
    - Delete button (and Delete/Backspace key when focus is not in an input) removes the selected shape; the text input edits the selected text shape's text
    - a load failure shows a non-blocking status message on the map and the map still renders; dismissing it works
    - store changes trigger network.redraw()
    - turning edit mode off keeps the draft and the drawing is still rendered
  </behavior>
  <action>
fakeVisNetwork.ts: add getNodeAt(pos) returning a public `nodeAtResult` (default undefined) and, if missing, redraw() incrementing `redrawCount`. Do not change existing behaviour.

TopologyMap.tsx (keep additions small; put geometry in mapDrawing.ts, not here):
- In the mount effect's beforeDrawing handler call drawGrid then drawShapes(ctx, useMapDrawingStore.getState().draft, selectedId only while edit mode is on, network.getScale()) -- reading the store via getState() so the once-registered handler always sees current data. Comment: beforeDrawing runs before vis-network draws edges and nodes, so the drawing is always behind them; same coordinate space as the grid.
- An effect subscribing to useMapDrawingStore (draft, selectedId) that calls networkRef.current?.redraw(), like the existing tierLookup redraw.
- An effect on mount that calls useMapDrawingStore.getState().load() once (store skips while dirty or in flight).
- When editMode turns false, set the store's tool to "none" and clear selection, but keep the draft (planner finding 3). Register a window beforeunload listener while dirty (preventDefault and set returnValue) and remove it when clean or on unmount.
- Pointer handling: an onPointerDownCapture on a wrapper around the containerRef div (or on the root div, excluding events whose target is inside the overlays). Engage only if editModeRef.current and tool is not "none" and network.getNodeAt(domPoint) is undefined, where domPoint is clientX/clientY minus the container's getBoundingClientRect. Then convert with network.DOMtoCanvas, call event.stopPropagation() and event.preventDefault() (keeps vis-network from panning or treating it as a click), call onActivityRef.current?.(), and: for rect/ellipse/line, create the shape at the snapped point and drag its far corner/endpoint; for text, create a text shape with text "Label", select it and switch the tool to "select" so the toolbar text input can edit it; for select, hitTest with tolerance 6 / scale (handles first) and start a move or resize drag, or clear the selection and let nothing else happen if no shape is hit. During the drag use window pointermove/pointerup listeners (removed on pointerup and on unmount), apply moveShape/resizeShape to the store; drop a zero-size rect/ellipse/line created by a plain click. Never call any checkmkWrite function from drawing code.
- Add an optional onActivity prop (ref pattern like onEditSavedRef), called for every drawing interaction and toolbar action.
- Render MapDrawingToolbar as an absolute overlay (top-right, z-10, not overlapping the zoom group at bottom-right or vis-network's manipulation bar at top-left) only when editMode is true. Render the load error, when present, as a small dismissible role="status" text in any mode (non-blocking, map still usable), and save errors inside the toolbar.

MapDrawingToolbar.tsx: reads and writes useMapDrawingStore; uses kone-design-system Button (check its exports in node_modules/kone-design-system before choosing components; plain buttons with aria-pressed are fine for tool toggles) and Tailwind classes consistent with TopologyToolbar. Contents: tool buttons None (hosts), Select, Rectangle, Ellipse, Line, Text (aria-pressed, accessible names); stroke swatches and fill swatches plus "No fill" from DRAWING_PALETTE (aria-label with colour name); when a text shape is selected, a text input (maxLength MAX_TEXT_LENGTH) and a font-size select from FONT_SIZES; Delete (disabled without selection); Revert (disabled when clean); Save (disabled when clean or saving; label "Saving…" while saving); an unsaved indicator "Unsaved drawing changes" when dirty. Keyboard Delete/Backspace on the map container deletes the selected shape when the event target is not an input, textarea or select.

IndexRoute.tsx: pass onActivity={touch} to TopologyMap. Nothing else.

Tests: TopologyMapDrawing.test.tsx for the map behaviours above (vi.mock "../lib/mapDrawingClient" with vi.fn loadDrawing/saveDrawing; reset the store in beforeEach; set the FakeNetwork's nodeAtResult via the instance the mock exposes the same way TopologyMap.test.tsx reaches its network), MapDrawingToolbar.test.tsx for the toolbar. If the new mount-time load makes existing suites noisy or failing (IndexRoute, App, TopologyMap tests calling a real relative fetch), add vi.mock of "../lib/mapDrawingClient" (resolving an empty drawing) in those specific files rather than changing the client.

README (dashboard-react/README.md section 5): add a "Drawing layer" subsection: what it is (Phase 15 groundwork, one shared drawing, no floors/towers/layers yet), tools and how resize/endpoint drag work, None-tool keeps host behaviour unchanged and host clicks always win, shapes snap to 25px, drawn behind nodes and read-only outside edit mode, Save/Revert/unsaved indicator, last write wins, draft kept when leaving edit mode or on idle timeout until Save/Revert or a reload (reload asks first), stored as /map-drawing.json on the map_drawing_data volume via nginx WebDAV PUT (json-only, 256 KB, file content validated on load), not available under the Vite dev server, and the rebuild + full down/up instruction.

Finally run the full checks from dashboard-react: npx vitest run (whole suite), npx tsc -b --noEmit (the repo's typecheck script; also acceptable npm run typecheck), npm run lint (oxlint), and one foreground npm run build. Fix anything this change broke.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard/dashboard-react && npx vitest run && npm run typecheck && npm run lint && npm run build</automated>
  </verify>
  <done>Full vitest suite, typecheck, oxlint and build pass; drawing renders in beforeDrawing behind nodes; tools only in edit mode; node drag/snap path unchanged (existing TopologyMap tests still pass untouched); Save/Revert/unsaved indicator work; README documents the feature.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| browser -> nginx /map-drawing.json | unauthenticated PUT from anyone who can reach the dashboard (closed demo network) |
| volume file -> browser | file content is untrusted input to the SPA (could be hand-edited or written by another client) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-eln-01 | Tampering | nginx location = /map-drawing.json | accept | Open write on a closed demo network, same trade-off as /admin-config.json and /triage-config.json; documented in the constraint amendment. Worst case is a defaced drawing; Checkmk and hosts are unaffected. |
| T-eln-02 | Elevation / Tampering | other paths and methods on nginx | mitigate | Exact-match location only; dav_methods PUT only there; limit_except GET PUT; create_full_put_path off; traversal normalised before matching; everything else falls to the static SPA location (PUT -> 405). |
| T-eln-03 | Denial of service | disk fill via PUT | mitigate | client_max_body_size 256k and a single fixed filename, so the volume holds at most one ~256 KB file (plus transient temp files). |
| T-eln-04 | Information disclosure / XSS | text labels rendered in the browser | mitigate | Text drawn with canvas fillText and shown in a React-controlled input only; never innerHTML or dangerouslySetInnerHTML; sanitizeDrawing strips control characters and caps length. |
| T-eln-05 | Denial of service | malformed or huge JSON breaking the map | mitigate | sanitizeDrawing drops unknown types and non-finite numbers, clamps coordinates and sizes, caps shapes at 500; load errors are non-blocking. |
| T-eln-06 | Tampering | content type smuggling | mitigate | map-based 415 for PUT that is not application/json. |
| T-eln-07 | Repudiation | who changed the drawing | accept | No auth exists to attribute; updated_at only. Same as other demo-network surfaces. |
</threat_model>

<verification>
- Task 1 grep/parse gate passes; nginx config syntax NOT verified locally (no nginx/podman on the dev machine) -- SUMMARY must say so and list the deploy-host checks: `podman run --rm docker.io/library/nginx:alpine nginx -V 2>&1 | tr ' ' '\n' | grep dav`, then after `podman compose build dashboard` and `podman compose down && podman compose up -d`: `curl -i http://localhost:8090/map-drawing.json` (404 before first save), `curl -i -X PUT -H 'Content-Type: application/json' --data '{"version":1,"updated_at":null,"shapes":[]}' http://localhost:8090/map-drawing.json` (201/204), `curl -i -X PUT -H 'Content-Type: text/plain' --data x http://localhost:8090/map-drawing.json` (415), `curl -i -X DELETE http://localhost:8090/map-drawing.json` (403), `curl -i -X PUT --data x http://localhost:8090/other.json` (405).
- Full dashboard-react vitest suite, typecheck, oxlint, build pass.
- No changes under analytics/, poller, deploy/mosquitto*, broker ACLs. No deploy, push, or container restarts.
</verification>

<success_criteria>
- Operator in edit mode can draw, select, move, resize, recolour, edit text, delete, Save and Revert; drawing persists in /var/lib/map-drawing/map-drawing.json on map_drawing_data and shows read-only for every viewer after reload.
- Host node dragging, grid snap and map_position persistence unchanged.
- Docs, README and the dated 2026-10-05 constraint amendment updated; SUMMARY records the DAV-module verification method and what could not be verified.
</success_criteria>

<output>
Create `.planning/quick/261005-eln-topology-map-drawing-layer-shapes-and-te/261005-eln-SUMMARY.md` when done
</output>
