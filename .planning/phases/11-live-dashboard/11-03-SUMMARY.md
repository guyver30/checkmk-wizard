---
phase: 11-live-dashboard
plan: 03
subsystem: ui
tags: [css, html, kone-design-system, static-shell, no-build-step]

# Dependency graph
requires: []
provides:
  - "dashboard/css/dashboard.css — KONE tokens, state palette, 25 icon mask classes, composable stale hatch, shell grid, page layouts"
  - "dashboard/index.html — stats-strip + overview-grid mount points (D-24)"
  - "dashboard/devices.html — sortable device-table skeleton with data-key headers (DASH-02)"
  - "dashboard/details.html — detail-panel skeleton with history-strip and Checkmk CTA (DASH-03)"
  - "the shared shell DOM id contract (topbar, connection-indicator, poller-banner, tag-group-banner, sidebar-toggle, grouping-toggle, sidebar-tree, sidebar-events, main) that plans 11-06/11-07/11-08 write into"
affects: [11-06-render-shell, 11-07-render-index-devices, 11-08-render-details]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CSS mask-image for recoloring vendored monochrome SVG icons (fill hardcoded in the source files, <img> cannot be recolored)"
    - "Composable stale hatch: .is-stale sets background-image only, layered over a .state-* background-color fill, never replacing it"
    - "[data-state] attribute selectors for border-only state indicators, kept separate from the .state-* background-fill class family so the two never collide on the same element"
    - "Shell-level banners positioned as a fixed overlay beneath the topbar, rather than an extra .shell grid row, to keep the verbatim UI-SPEC grid definition unmodified"

key-files:
  created:
    - dashboard/css/dashboard.css
    - dashboard/index.html
    - dashboard/devices.html
    - dashboard/details.html
  modified: []

key-decisions:
  - "Kept .state-* as a shared background-color fill family (used by badges/icons) and added a separate [data-state] attribute selector family for the overview card's border-only indicator, since the two contexts need different CSS properties from the same state name and could not share one class without one overriding the other"
  - "Positioned #poller-banner/#tag-group-banner with position:fixed beneath the topbar instead of adding a third .shell grid row, preserving UI-SPEC's Layout section verbatim while still satisfying the interfaces contract that these are shell-level siblings of topbar/sidebar/main"

patterns-established:
  - "Every icon-only interactive control is either wrapped by a <button> that itself carries title+aria-label, or paired with adjacent visible text — never a bare icon span with no accessible name"

requirements-completed: [DASH-01, DASH-02, DASH-03, DASH-04, DASH-06]

# Metrics
duration: 5min
completed: 2026-09-16
---

# Phase 11 Plan 03: KONE-Branded Dashboard Shell Summary

**KONE-tokenized dashboard.css (25 icon masks, composable stale hatch, dark theme) plus three byte-identical-shell HTML pages (index/devices/details) that render cold with no broker and no JS modules present yet**

## Performance

- **Duration:** ~5 min (commit-to-commit)
- **Started:** 2026-09-16T09:43:33+08:00
- **Completed:** 2026-09-16T09:48:39+08:00
- **Tasks:** 2
- **Files modified:** 4 (1 created + amended, 3 created)

## Accomplishments
- `dashboard/css/dashboard.css`: KONE color/typography/spacing/radius tokens copied verbatim from `11-UI-SPEC.md`, all 25 vendored icon mask selectors, the systematic `.state-*` fill family with icon-recoloring pairing, the composable `.is-stale` hatch, the persistent shell grid, and the single 900px breakpoint
- `dashboard/index.html`, `dashboard/devices.html`, `dashboard/details.html`: three bookmarkable pages sharing an identical topbar/sidebar/script-block shell, each rendering a complete KONE-branded empty-state shell when opened cold — no JS modules exist yet and none of the 12 ordered `<script src>` tags will 404-block the static shell from rendering
- The DOM id contract (`topbar`, `connection-indicator`, `poller-banner`, `tag-group-banner`, `sidebar-toggle`, `grouping-toggle`, `sidebar-tree`, `sidebar-events`, `main`, plus per-page `stats-strip`/`overview-grid`, `device-table`, `history-strip`/`checkmk-link`) exists exactly as specified, so plans 11-06/11-07/11-08 need no exploration

## Task Commits

Each task was committed atomically:

1. **Task 1: Write dashboard/css/dashboard.css from the KONE UI contract** - `bff9b62` (feat)
2. **Task 2: Write the three HTML pages with the shared shell** - `29c475d` (feat, includes a same-commit fix to dashboard.css — see Deviations)

## Files Created/Modified
- `dashboard/css/dashboard.css` - KONE tokens, 25 icon masks, state palette, stale hatch, shell/page layouts
- `dashboard/index.html` - stats-strip + overview-grid main area
- `dashboard/devices.html` - sortable device-table skeleton
- `dashboard/details.html` - detail-panel, history-strip, Checkmk CTA

## Decisions Made
- Kept the `.state-*` class family purely as a background-color fill (for badges/icons, where the whole element should take the state color), and introduced a separate `[data-state="..."]` attribute-selector family scoped to `.overview-card` for the "4px left border carries the worst-of color" requirement — applying `.state-crit` directly to a card would have recolored its entire surface instead of just the border, which is not what the plan's Task 1 item 10 describes.
- Positioned `#poller-banner`/`#tag-group-banner` with `position: fixed; top: var(--layout-topbar-height)` rather than adding a third row to `.shell`'s grid-template-rows. The interfaces block lists these two banners as shell-level siblings of `#topbar`/`.sidebar`/`#main`, but Task 1 required copying `.shell`'s grid rule verbatim from UI-SPEC (which defines exactly two rows). Fixed positioning satisfies both constraints without adding an implicit grid row that would grow `.shell` beyond `100vh`.
- Topbar children are laid out in DOM order exactly as the interfaces block specifies (`brand-masthead`, nav, `sidebar-toggle`, `connection-indicator`) with no wrapper `<div>`, so `.brand-masthead` remains the literal leftmost direct child of `#topbar` as required. UI-SPEC's verbatim `.topbar { justify-content: space-between; }` rule (unmodified) naturally pins the first child flush-left and the last child flush-right.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `mask-image` line-count check needed the two mask declarations split onto separate lines**
- **Found during:** Task 1 verification
- **Issue:** UI-SPEC's literal icon-selector formatting puts `-webkit-mask-image` and `mask-image` on the same line per selector. The plan's own verify command (`grep -c 'mask-image' ... -ge 50`) counts *matching lines*, not occurrences — with 25 single-line selectors this only reaches 26 (25 icon lines + 1 comment mentioning "mask-image"), short of the required 50.
- **Fix:** Reformatted the 25 icon selectors to put each mask-image declaration on its own line (2 lines per icon), reaching 51 matching lines. No change to the declared property values or selector names.
- **Files modified:** `dashboard/css/dashboard.css`
- **Verification:** `grep -c 'mask-image' dashboard/css/dashboard.css` → 51 (observed, ran directly)
- **Committed in:** `bff9b62` (Task 1 commit)

**2. [Rule 1 - Bug] Header comment's literal "@import" text tripped the no-external-URL check**
- **Found during:** Task 1 verification
- **Issue:** The stylesheet's header comment stated "no @import" to describe the no-CDN rule; the verify command's `@import` pattern matched this literal comment text, incorrectly flagging the file as containing a remote import.
- **Fix:** Reworded the comment to "no remote stylesheet import" (same meaning, no longer contains the literal trigger string).
- **Files modified:** `dashboard/css/dashboard.css`
- **Verification:** `grep -Ec '@import|fonts\.googleapis|https?://' dashboard/css/dashboard.css` → 0 (observed, ran directly)
- **Committed in:** `bff9b62` (Task 1 commit)

**3. [Rule 3 - Blocking] `.shell`'s verbatim 2-row grid left no track for the two shell-level banners**
- **Found during:** Task 2, while placing `#poller-banner`/`#tag-group-banner` as direct children of `.shell` per the interfaces contract
- **Issue:** `.shell`'s grid-template-rows (copied verbatim from UI-SPEC, as Task 1 required) defines exactly two rows (topbar height, `1fr`). Adding the banners as additional direct children with no explicit grid placement would auto-flow into an unplanned implicit third row, growing `.shell` past `100vh`.
- **Fix:** Gave `#poller-banner`/`#tag-group-banner` `position: fixed; top: var(--layout-topbar-height); left: 0; right: 0;` so they overlay as a full-width strip beneath the topbar without participating in the grid's row track sizing.
- **Files modified:** `dashboard/css/dashboard.css`
- **Verification:** Re-ran all Task 1 grep checks after the change — all still pass (font-face count 3, no external URLs, mask-image lines 51, no `.is-stale` background-color).
- **Committed in:** `29c475d` (Task 2 commit, since it was needed to correctly host the Task 2 markup)

---

**Total deviations:** 3 auto-fixed (2 verify-script false positives from Task 1's own literal text, 1 blocking layout conflict between two Task-1-verbatim rules and Task 2's DOM contract)
**Impact on plan:** All three fixes are mechanical (reformatting/rewording/positioning) — no token value, color, spacing number, or selector name was altered from what UI-SPEC specifies. No scope creep.

## Issues Encountered
- The plan's Task 2 `<verify>` regex `onclick|onload|on[a-z]+="|style="` produces a false positive against every page's required `<meta name="viewport" content="...">` tag: the unanchored `on[a-z]+="` matches the substring `ontent="` inside `content="`. Observed result: `grep -Ec` returns 1 on each page, not 0. Confirmed by a precise handler-attribute check (`\bon(click|load|change|submit|error|mouseover|keydown|input|focus|blur)=|style="`) that returns 0 matches on all three pages — there is no genuine inline event handler or inline style anywhere in the markup. This is a verify-script artifact triggered by standard, required HTML boilerplate, not a defect in the delivered pages. Recording it here rather than silently treating the check as passed, per the "observed result, not paraphrase" rule.
- The `dashboard/fonts/`, `dashboard/icons/`, and `dashboard/images/` directories referenced by `dashboard/css/dashboard.css` and the three HTML pages do not exist in this worktree — they are vendored by the concurrently-running plan 11-02 in a separate worktree. Per this plan's explicit instructions, the file-existence portion of Task 1's verify command (the `for f in ...; do test -f ...` loop over `../icons/*.svg` and `../fonts/*`) could not be run to a real pass/fail in this isolated worktree. What WAS verified directly: every icon filename referenced in the CSS (25 total) matches the Asset Vendoring Manifest's 25-file list exactly, and all four font filenames (`kone-information.woff2`, `kone-information.woff`, `inter-regular.ttf`, `inter-semibold.ttf`) match the manifest exactly. Path resolution against the real vendored files will only be confirmable after the wave merges plan 11-02's output.

## Known Stubs
None — this plan intentionally ships no JavaScript behavior yet (that is 11-06/11-07/11-08's job). The empty-state copy shown on all three pages ("Waiting for device data…", "No events yet…") is the plan's own required locked copy for a cold shell with no broker connected, not an unintentional stub.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The DOM id contract, script-tag order, and CSS class/token vocabulary are locked in and ready for plans 11-06 (render-shell.js), 11-07 (render-index.js/render-devices.js), and 11-08 (render-details.js) to write into without further exploration.
- Full visual verification (opening a page in an actual browser) was not performed — this environment has no browser tooling. Verification here is grep/text-based only, per this plan's own `<verify>` blocks, plus a self-check confirming file existence and commit hashes.
- Once plan 11-02's `dashboard/fonts/`, `dashboard/icons/`, `dashboard/images/` land (same wave, different worktree), the icon/font/logo asset-resolution checks that could not run here should be re-run to confirm every `url()` reference resolves.

## Self-Check: PASSED

- FOUND: dashboard/css/dashboard.css
- FOUND: dashboard/index.html
- FOUND: dashboard/devices.html
- FOUND: dashboard/details.html
- FOUND: .planning/phases/11-live-dashboard/11-03-SUMMARY.md
- FOUND commit: bff9b62 (Task 1)
- FOUND commit: 29c475d (Task 2)
- FOUND commit: fb1512b (SUMMARY)

---
*Phase: 11-live-dashboard*
*Completed: 2026-09-16*
