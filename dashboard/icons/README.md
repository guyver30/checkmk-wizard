# Vendored: KONE icons

**Source:** `web_assets/kone-design-system-main/packages/kone-ds-assets/icons/`
**Copied:** 2026-09-16

Internal KONE design-system files, copied verbatim from the checkout — not a
package-registry dependency, so no legitimacy audit applies (see
`.planning/phases/11-live-dashboard/11-UI-SPEC.md` "Registry Safety").

Exactly 25 of the source folder's 207 SVGs are vendored here, hand-picked for the three
pages this phase builds; filenames are unchanged from source. See
`.planning/phases/11-live-dashboard/11-UI-SPEC.md`'s Asset Vendoring Manifest for the
full file list and per-icon usage.

Every vendored SVG hardcodes `fill="#141414"` in its path data rather than using
`fill="currentColor"` (confirmed by inspecting `good-filled.svg`), which is why these are
referenced via CSS `mask-image` rather than `<img src="...">` — see UI-SPEC's
"Iconography" section.
