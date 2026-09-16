# Vendored: KONE fonts

**Source:** `web_assets/kone-design-system-main/packages/kone-ds-fonts/src/fonts/`
**Copied:** 2026-09-16

Internal KONE design-system files, copied verbatim from the checkout — not a
package-registry dependency, so no legitimacy audit applies (see
`.planning/phases/11-live-dashboard/11-UI-SPEC.md` "Registry Safety").

| Source file | Destination |
|---|---|
| `KONE Information.woff2` | `kone-information.woff2` |
| `KONE Information.woff` | `kone-information.woff` |
| `Inter-Regular.ttf` | `inter-regular.ttf` |
| `Inter-SemiBold.ttf` | `inter-semibold.ttf` |

Not vendored: `KONE Information.eot`/`.svg`/`.ttf` (legacy formats, no target browser on
this LAN needs them) and the entire `Kone-icons` icon webfont (see `dashboard/icons/`
instead — individual SVGs, not a webfont).
