# Dashboard design mockup — the approved Phase 11.1 target

**This is a design contract, not shipping code.** Nothing here is served to
operators and nothing here is loaded by `dashboard/`. It exists so the layout and
palette the operator approved on 2026-09-16 are recorded in git rather than living
only in a session scratchpad.

Phase 11.1 implements what this shows. Where this mockup and
`.planning/phases/11-live-dashboard/11.1-SCOPE.md` disagree, the scope document
wins — it carries the reasoning; this carries the appearance.

## What it is

A harness that loads the **real** dashboard modules from `../../dashboard/js/`
against a **synthetic** data feed, with preview-only overrides layered on top. The
point of running the real modules is that the mockup cannot drift into showing
something the actual code could never do.

| File | Role | Becomes |
|---|---|---|
| `css/preview-light.css` | The KONE light palette, contrast-audited | Folded into `dashboard/css/dashboard.css` (11.1 item 1) |
| `css/preview-layout.css` | Three-pane layout: tree left full-height, centre split | Folded into `dashboard.css` (11.1 item 2) |
| `js/preview-events.js` | Event history relocated to the centre, filtered to the selected device | Reworked into the real render path (11.1 item 2) |
| `js/preview-feed.js` | Synthetic fleet on the real MQTT contract | **Never ships** — the real poller replaces it |
| `js/preview-chrome.js` | Harness bar, view switching, `#main` swapping | **Never ships** — scaffolding only |
| `js/preview-map.js` | Topology map mockup | **Phase 13**, not 11.1 |
| `css/preview-phase12.css`, `js/preview-phase12.js` | Agent metrics / per-service placeholder | **Phase 12**, not 11.1 |

The last three rows matter: this mockup deliberately shows **three phases at
once** so the operator could judge the whole shape. Only the first three rows are
Phase 11.1.

## Running it

It needs the real `dashboard/` assets alongside it, so serve from a directory where
both are reachable, or copy `dashboard/{css,js,fonts,icons,images}` next to it.
The simplest approach used during design was a flat copy plus:

```bash
cd <mockup-dir> && uv run python -m http.server 8777
```

`js/vendor/vis-network.min.js` (~650 KB, used only by the Phase 13 map mockup) is
NOT committed here. Fetch it if the map is wanted:

```bash
curl -o js/vendor/vis-network.min.js \
  https://unpkg.com/vis-network@10.1.2/standalone/umd/vis-network.min.js
```

That is the exact version Phase 13 plans to vendor.

## What the operator approved

- **White/KONE light palette**, sourced from KONE's own `design-tokens.json`
- **Left column is all tree**, full height — never disappears, only re-groups
- **Centre splits**: map or device details on top, event history beneath
- **Event history is always visible** and filters to the selected device
- **KONE logo prominent** in the page header
- **No "Details" nav item** — a device is reached by clicking it
- Grouping becomes a combo (`type` / `folder`) plus an **Order by severity** checkbox
- All three panes **resizable and collapsible** (not yet designed — see the scope doc)

## Known mockup-only compromises

These exist because it is a harness, and must NOT be copied into the real build:

- `preview-chrome.js` wraps `history.pushState` to emit its own event. The real
  `shell.js` needs no such thing — it calls `mountView()` directly after
  `pushState`.
- `preview-chrome.js` swaps `#main`'s markup per view because a single page has to
  stand in for three. The real build has three pages.
- The harness bar (fixed, bottom) is scaffolding.
- `preview-events.js` re-implements event rows rather than reusing
  `render-shell.js`'s, because the real one targets `#sidebar-events`. In 11.1 the
  real renderer moves; it should not be duplicated.
