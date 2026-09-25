# Device-type icons

The dashboard shows an icon per host, chosen by the host's **device type**. Icons are plain SVG
files you drop into a folder — there is no code to edit.

## Where things are

| What | Path |
|------|------|
| List of device types (the Checkmk `device_type` tag choices) | `device_types.json` (repo root) |
| Icon files, one per device type | `dashboard-react/src/assets/icons/device-types/<device_type>.svg` |
| Code that loads them (no edit needed) | `dashboard-react/src/lib/mapIcons.ts` |

Current types: `other`, `E-link`, `ACS`, `Multimedia`, `NetworkDevice`, `GroupController`.

## The rule

**The icon's file name is the device type**, exactly and case-sensitively:
`E-link` → `E-link.svg`, `NetworkDevice` → `NetworkDevice.svg`.

A device whose type has no matching file shows `other.svg`, so `other.svg` must always exist.

## Change an icon

1. Overwrite `dashboard-react/src/assets/icons/device-types/<device_type>.svg`.
2. Rebuild the dashboard (below).

## Add an icon for a new device type

1. Add the type name to `device_types.json`. Keep `"other"` as the **first** entry — the wizard
   refuses to run otherwise (Checkmk gives every untagged host the first listed value).
2. Save the icon as `dashboard-react/src/assets/icons/device-types/<NewType>.svg`.
3. Rebuild the dashboard (below).
4. **On a site that already exists**, also add the new choice to the `device_type` tag group in
   Checkmk (*Setup → Tags → Host tag groups → device_type*, then activate changes). The wizard only
   creates that tag group once and never updates its choice list, so editing `device_types.json`
   alone does not change an existing site. A brand-new site picks the list up automatically.

## SVG requirements

- Square `viewBox`; the shipped icons are 16×16 (`viewBox="0 0 16 16"`).
- Root element `<svg … fill="none">`, with the glyph shapes filled with **exactly**
  `fill="#141414"`.
- Single colour only. The dashboard swaps `#141414` for the host's state colour on the map
  (green/orange/red/grey) and uses the icon as a mask in the sidebar tree, so gradients,
  multiple colours, strokes-only glyphs or embedded images will not recolour correctly.

Easiest start: copy an existing file and replace its `<path>` data.

## Rebuild / preview

Icons are bundled at build time, so a change is visible only after a rebuild.

- Quick look while editing: `cd dashboard-react && npm run dev`.
- Deployed dashboard: rebuild and redeploy the `dashboard` container as usual (build
  prerequisites are in [`dashboard-react/README.md`](../dashboard-react/README.md) §2–3).

## Troubleshooting

| Symptom | Cause |
|---------|-------|
| New icon not showing | Dashboard not rebuilt, or the file name does not match the type exactly (check case). |
| Icon shows as the `other` circle | No file named after that type, or the host's type is `unknown` (tag group missing on the site — add `unknown.svg` if you want a distinct icon). |
| Icon stays black/grey and ignores state colour | Glyph fill is not exactly `fill="#141414"`. |
| Wizard aborts: "first entry must be 'other'" | `device_types.json` was reordered. |
