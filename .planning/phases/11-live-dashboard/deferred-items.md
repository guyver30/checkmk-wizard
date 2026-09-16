# Deferred Items — Phase 11 (live-dashboard)

Items discovered during plan execution that are out of the discovering plan's
`files_modified` scope and were therefore documented here rather than fixed inline.

## 1. `dashboard/js/shell.js` line 15 wipes every `ViewModules.*` registration on load

- **Discovered during:** 11-08 (`dashboard/js/render-details.js`), Task 1 implementation review
- **File:** `dashboard/js/shell.js` (created by plan 11-06, already merged — out of 11-08's
  `files_modified: [dashboard/js/render-details.js]`)
- **Root cause:** `shell.js` line 15 is `var ViewModules = {};` — an unconditional
  reassignment, not a defensive `var ViewModules = ViewModules || {};` guard. In all three
  HTML files (`index.html`, `devices.html`, `details.html`), `shell.js`'s `<script>` tag is
  the *last* one loaded, after `render-index.js`, `render-devices.js`, and
  `render-details.js` have each already run and set `ViewModules.index` /
  `ViewModules.devices` / `ViewModules.details`. Because non-module `<script>` tags execute
  synchronously in document order and share one global scope, `shell.js`'s own
  `var ViewModules = {};` statement re-executes at that later point in program order and
  discards the object those three earlier scripts already populated — verified with a
  two-script Node `vm` simulation reproducing the same load order (first script does
  `var ViewModules = ViewModules || {}; ViewModules.details = "X";`, second script does
  `var ViewModules = {};`; the result is `{}`, not `{details: "X"}`).
- **Impact:** By the time `shell.js`'s own `DOMContentLoaded` handler calls
  `mountView(view, params)` (`ViewModules[view].mount(...)`), `ViewModules` is the empty
  object `shell.js` itself just created — `ViewModules[view]` is `undefined` for every view
  on every page, on first load. `shell.js`'s `mountView()` already has a defensive branch for
  exactly this shape (`if (!module) { console.error(...); return; }`), so nothing throws, but
  no page ever actually mounts its view module: `index.html`/`devices.html`/`details.html`
  would all show only their static empty-state markup and never call `mount()`,
  `update()`, or `unmount()`. This was not caught during 11-06's own verification because
  that plan's environment had no browser available and validated `shell.js` with `node --check`
  plus grep-assertion harnesses only — never an actual multi-`<script>`-tag load in order.
- **Recommended fix (for whoever owns `shell.js` next, e.g. a gap-fix plan or 11-06 patch):**
  Change `dashboard/js/shell.js` line 15 from `var ViewModules = {};` to
  `var ViewModules = ViewModules || {};`, matching the guard `dashboard/js/render-details.js`
  already uses. This one-line change is enough: it makes `shell.js` reuse whatever object the
  earlier render-*.js scripts already built, instead of replacing it.
- **Not fixed here because:** `dashboard/js/shell.js` is outside 11-08's `files_modified`
  (`dashboard/js/render-details.js` only), was authored and merged by a different, already-
  completed plan (11-06), and this worktree runs in parallel with sibling agents — editing a
  shared, already-merged file outside this plan's declared scope risks colliding with
  concurrent work and violates the plan's atomic-commit/file-scope discipline.
- **Verification this plan performed instead:** `dashboard/js/render-details.js`'s own
  `ViewModules.details` registration and `mount`/`update`/`unmount` behavior were verified
  directly with a Node `vm` harness that stubs the DOM and globals `shell.js` would otherwise
  provide (see 11-08-SUMMARY.md) — i.e., this plan proved its own file is correct in
  isolation; the `shell.js` defect above is what would prevent that correct module from ever
  being invoked by a real page load until the one-line fix above lands.
