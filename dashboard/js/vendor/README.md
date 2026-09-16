# Vendored: mqtt.js

**Package:** `mqtt@5.15.2` (browser UMD build, minified)
**Source:** https://unpkg.com/mqtt@5.15.2/dist/mqtt.min.js
**Downloaded:** 2026-09-16
**File:** `mqtt.min.js` — downloaded verbatim, not hand-edited or reformatted.

## Why vendored instead of loaded from a CDN

D-03 (`.planning/phases/11-live-dashboard/11-CONTEXT.md`): the dashboard must work on a
monitoring LAN with no internet egress, so every runtime asset has to resolve from the
dashboard's own origin. Committing the file also pins the exact bytes by content, rather
than trusting a CDN to keep serving the same version indefinitely.

## Legitimacy audit

Already performed in `.planning/phases/11-live-dashboard/11-RESEARCH.md`'s Package
Legitimacy Audit table: `mqtt` (mqttjs/MQTT.js), npm, ~10 years old, tens of millions of
weekly downloads, source repo verified (`npm view mqtt repository.url` →
`git://github.com/mqttjs/MQTT.js.git`), `slopcheck` verdict `[OK]`. Not re-audited here.
