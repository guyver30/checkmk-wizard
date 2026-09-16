# Deferred Items — Phase 11 (live-dashboard)

Items discovered during plan execution that are out of the discovering plan's
`files_modified` scope and were therefore documented here rather than fixed inline.

## 1. [RESOLVED 2026-09-16, commit `6191395`] `dashboard/js/shell.js` line 15 wipes every `ViewModules.*` registration on load

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
- **Resolution:** fixed 2026-09-16 during wave 4 (commit `6191395`), exactly as recommended
  above — `var ViewModules = ViewModules || {};`. See `11-06-SUMMARY.md`'s "Post-Mortem" section
  (added by plan 11-09) for the full impact analysis and the lesson this bug leaves behind: every
  file involved was individually valid (`node --check` passed on all of them) — only the
  *composition* of independently-correct files, loaded in a fixed script order, was broken, which
  no static/grep check could see. 11-07's `render-index.js`/`render-devices.js` deferring their
  own registration into `DOMContentLoaded` is now a redundant-but-harmless second registration
  style that coexists with the guard; not worth a churn-only cleanup.

---

## Retrospective Notes (added 2026-09-16, plan 11-09)

Not deferred fixes — observations recorded for future plan design in this and later phases.

**Grep-verification measures text, not behavior.** Six of this phase's nine plans reshaped
comment prose or statement formatting purely to satisfy literal greps in their own `<verify>`
blocks: padding a comment so `grep -c` hit a count, splitting CSS declarations onto separate
lines because `grep -c` counts lines not occurrences, rewording comments containing
`innerHTML`/`localStorage`/`@import` to dodge a substring match, deleting emoji from comments.
Meanwhile the one real defect this phase produced (item 1 above) lived entirely in file
*composition* — three individually-valid files interacting in a fixed load order — which no grep
addressed, because no single file's text was wrong. Lesson for future plan design: acceptance
criteria should measure observable behavior (a real page load, a function's return value, a
rendered DOM) wherever that is achievable, not the literal text of source comments — a grep gate
on comment wording can pass while the code it describes is broken, and can fail while the code is
correct, for reasons unrelated to correctness.

**Closing the CSS gap took three passes because no single plan owned it.**
`dashboard/css/dashboard.css` was authored in wave 1 (plan 11-03), while the JS and markup that
invent the class names it must cover landed in waves 3-4 (plans 11-06 through 11-08) — so no
individual plan's `files_modified` scope included "verify every class referenced by the JS has a
matching CSS rule." What finally bounded it was a full sweep enumerating every class referenced
across `dashboard/js/*.js` and diffing against the stylesheet (45 classes referenced, 42 covered,
3 intentionally uncovered — `.connection-text`, `.poller-banner-text`, `.tag-group-banner-text`
are plain spans inheriting styling from their containers, not a gap). A stylesheet authored before
the markup/JS that will reference it is a recurring risk in a plan set split by wave rather than
by feature; a later plan set with the same shape should either author CSS after its consumers, or
budget an explicit closing-sweep plan up front rather than discovering the need for one mid-phase.
