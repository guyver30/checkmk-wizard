---
phase: 11-live-dashboard
plan: 02
subsystem: ui
tags: [static-assets, mqtt-js, nginx, kone-design-system, compose]

# Dependency graph
requires:
  - phase: 09-poller-core
    provides: the MQTT topic contract this dashboard will consume from plan 04 onward
  - phase: 08-broker-infrastructure-hardening
    provides: mosquitto WebSockets listener, wsreader/topic-read-only credential convention
provides:
  - Vendored mqtt.js 5.15.2 browser UMD bundle at dashboard/js/vendor/mqtt.min.js
  - Vendored KONE Information + Inter fonts at dashboard/fonts/
  - 25 vendored monochrome icon SVGs at dashboard/icons/
  - Whitespace-trimmed KONE logo at dashboard/images/kone-logo.png
  - dashboard/js/config.js: single per-deployment settings file
  - dashboard nginx service in deploy/compose.yaml on host port 8090
affects: [11-03, 11-04, 11-05, 11-06, 11-07, 11-08, 11-09]

# Tech tracking
tech-stack:
  added: [mqtt.js 5.15.2 (vendored browser UMD, no package manager)]
  patterns:
    - "dashboard/js/config.js as the browser-side analogue of a compose environment: block — one file operators edit per deployment"
    - "Vendor-once-and-commit for assets with no internet egress at runtime (mirrors D-03's mqtt.js precedent, extended to fonts/icons/logo)"

key-files:
  created:
    - dashboard/js/vendor/mqtt.min.js
    - dashboard/js/vendor/README.md
    - dashboard/fonts/kone-information.woff2
    - dashboard/fonts/kone-information.woff
    - dashboard/fonts/inter-regular.ttf
    - dashboard/fonts/inter-semibold.ttf
    - dashboard/fonts/README.md
    - dashboard/icons/*.svg (25 files)
    - dashboard/icons/README.md
    - dashboard/images/kone-logo.png
    - dashboard/js/config.js
  modified:
    - deploy/compose.yaml

key-decisions:
  - "Logo trim used a diff-against-solid-white bbox instead of a bare Image.getbbox(), because the source PNG is RGB with no alpha and a flat white background, which makes getbbox() return the full 1000x1000 canvas"
  - "8090 port comment split across two lines so the D-04 rationale and the port number both land in the same grep-able line count style as the file's other multi-line port comments"

requirements-completed: [DASH-05, DASH-06]

# Metrics
duration: 4min
completed: 2026-09-16
---

# Phase 11 Plan 02: Vendor Assets and Dashboard Config Summary

**Vendored mqtt.js 5.15.2, four KONE/Inter fonts, 25 KONE icon SVGs, and a whitespace-trimmed KONE logo into `dashboard/`, plus one `config.js` settings file and a new `dashboard` nginx compose service on host port 8090.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-09-16T09:39:00+08:00 (approx, first download)
- **Completed:** 2026-09-16T09:42:56+08:00
- **Tasks:** 3
- **Files modified:** 35 (32 new dashboard asset files + 2 config/vendor files + deploy/compose.yaml)

## Accomplishments
- `dashboard/js/vendor/mqtt.min.js` downloaded verbatim from unpkg at the pinned 5.15.2 version, valid per `node --check`, with provenance recorded
- All 4 required KONE/Inter font files and exactly 25 named icon SVGs copied verbatim from `web_assets/`, with the excluded files (legacy KONE Information formats, the Kone-icons webfont, the other ~182 unreferenced icons) correctly left out
- KONE logo trimmed from 1000x1000 to 720x279 using a uv-managed Pillow one-off script, working around the RGB-no-alpha `getbbox()` pitfall this environment's notes flagged
- `dashboard/js/config.js` created as a classic script holding every per-deployment setting (WS credentials/port, poll interval, staleness factor, Checkmk base URL/site), with the disposable-credential and rotate-before-exposing disclosure required by D-01/T-11-04
- `deploy/compose.yaml` gained a sixth service, `dashboard` (nginx:alpine, read-only bind mount, host port 8090, no environment block), matching the file's existing structure and per-port comment convention

## Task Commits

Each task was committed atomically:

1. **Task 1: Vendor mqtt.js 5.15.2 browser UMD** - `363fede` (feat)
2. **Task 2: Vendor the KONE fonts, the 25 icons, and the trimmed logo** - `01b96f6` (feat)
3. **Task 3: Write dashboard/js/config.js and add the dashboard nginx service** - `dc8ae3c` (feat)

_No TDD tasks in this plan; no plan-metadata commit is added here per the worktree/parallel-execution instructions (STATE.md/ROADMAP.md updates are owned by the orchestrator after all wave agents complete)._

## Files Created/Modified
- `dashboard/js/vendor/mqtt.min.js` - Vendored mqtt.js 5.15.2 browser UMD bundle (369KB, verbatim download)
- `dashboard/js/vendor/README.md` - Provenance: source URL, download date, D-03 rationale, prior legitimacy-audit reference
- `dashboard/fonts/kone-information.woff2`, `kone-information.woff`, `inter-regular.ttf`, `inter-semibold.ttf` - Vendored fonts, renamed to lowercase kebab-case
- `dashboard/fonts/README.md` - Provenance for the fonts
- `dashboard/icons/*.svg` (25 files: good-filled, warning-triangle-filled, bad-filled, close-circle-filled, question-circle-filled, question-circle, status-unavailable, clock, pause-filled, check-circle-filled, warning-circle-filled, info-filled, close-cross, refresh, filter, list, pop-out, caret-up-small, caret-down-small, internet, api, secured, videocam, controls, circle) - Vendored icon SVGs, filenames unchanged from source
- `dashboard/icons/README.md` - Provenance, plus the `fill="#141414"` hardcoding note explaining why `mask-image` (not `<img>`) is required downstream
- `dashboard/images/kone-logo.png` - Whitespace-trimmed KONE logo (1000x1000 -> 720x279)
- `dashboard/js/config.js` - WS_PORT, WS_USERNAME, WS_PASSWORD, POLL_INTERVAL_SECONDS, STALENESS_FACTOR, HISTORY_MAX_ENTRIES, CHECKMK_BASE_URL, CHECKMK_SITE
- `deploy/compose.yaml` - Added the `dashboard` service (nginx:alpine, `../dashboard:/usr/share/nginx/html:ro,z`, `8090:80`, `cmk_net`)

## Decisions Made
- Used a diff-against-solid-white-image bounding box for the logo trim rather than a bare `Image.getbbox()` call, per this environment's documented pitfall (the source PNG has no alpha channel, so a bare `getbbox()` on it returns the full canvas rather than the visible content's extent). Verified the result is strictly smaller than the source in both dimensions (720x279 < 1000x1000) before committing.
- Split the `8090` port comment across two lines (matching the file's own multi-line comment style used elsewhere, e.g. the mosquitto WS port) so the D-04 rationale reads naturally across two lines while still satisfying the plan's line-count-based verification.

## Deviations from Plan

None - plan executed exactly as written. All three tasks' actions, verify commands, and acceptance criteria were followed and passed without needing Rule 1-4 fixes.

## Issues Encountered
None. The mqtt.js download succeeded on the first attempt (this machine had the one-time internet egress the plan anticipated might be unavailable), and the uv/Pillow logo-trim path worked as specified in the plan and the critical-environment-notes.

## User Setup Required

None - no external service configuration required. `dashboard/js/config.js`'s `CHECKMK_BASE_URL` placeholder (`http://<HOST_IP>:8080`) will need to be edited per deployment before the dashboard is used live, as documented in the file's own header comment, but that is an operator deployment step, not a setup task for this plan.

## Next Phase Readiness
- `dashboard/` now has every vendored asset (fonts, icons, logo, mqtt.js) and the one settings file (`config.js`) that plans 11-03 through 11-09 will build the actual HTML/CSS/JS shell, pages, and rendering logic against.
- `deploy/compose.yaml` has the `dashboard` service ready; `podman compose up -d` would bring it up on host port 8090 with no build step, though this was not run live in this plan (no server/container lifecycle command was part of any task's verify step).
- No blockers for the next plan in wave 1.

## Self-Check: PASSED

All created files verified present on disk (dashboard/js/vendor/mqtt.min.js and README.md,
all 4 fonts and README.md, 25 icon SVGs and README.md, dashboard/images/kone-logo.png,
dashboard/js/config.js, this SUMMARY.md). All 4 commit hashes (363fede, 01b96f6, dc8ae3c,
e2561e1) confirmed present in `git log`.

---
*Phase: 11-live-dashboard*
*Completed: 2026-09-16*
