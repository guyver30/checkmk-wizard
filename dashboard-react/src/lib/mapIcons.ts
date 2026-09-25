// Device-type icon recoloring for the topology map's vis-network canvas nodes. Every state's
// fill color is transcribed literally from 13-UI-SPEC.md's State palette table -- canvas code
// cannot read CSS custom properties the way the DOM's Badge/StateBadge components do, so this
// module is the one place these hex values are allowed to be hard-coded rather than read from
// design-system/src/tokens.css.
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only.

// 13-UI-SPEC.md "State palette for map nodes" -- CRIT/UNREACH/DOWN share one hex (differentiated
// by node border instead, see nodeVisual()); STALE shares PEND's hex (both neutral).
export const STATE_HEX: Record<string, string> = {
  OK: "#22c55e",
  WARN: "#f97316",
  CRIT: "#e5252a",
  UNREACH: "#e5252a",
  DOWN: "#e5252a",
  UNKNOWN: "#111114",
  PEND: "#55555f",
  STALE: "#55555f",
};

// Drop-in device-type icons: every `assets/icons/device-types/<device_type>.svg` is picked up at
// build time, and the file name (minus `.svg`, case-sensitive) IS the `tag_device_type` value
// from device_types.json. Adding or replacing an icon is a file drop -- no code edit. `other.svg`
// is the fallback for missing/unknown types, so it must exist.
const ICON_MODULES = import.meta.glob("../assets/icons/device-types/*.svg", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const DEVICE_TYPE_SVG: Record<string, string> = Object.fromEntries(
  Object.entries(ICON_MODULES).map(([path, markup]) => [
    path.slice(path.lastIndexOf("/") + 1, -".svg".length),
    markup,
  ]),
);

export function deviceTypeSvg(deviceType: string | null | undefined): string {
  return (deviceType && DEVICE_TYPE_SVG[deviceType]) || DEVICE_TYPE_SVG.other;
}

// CSS `mask-image` value for DOM surfaces (sidebar tree): the glyph takes the surrounding text
// color via `background-color: currentColor`, so it needs no per-state recoloring.
export function deviceTypeMaskUrl(deviceType: string | null | undefined): string {
  return `url("${recoloredDataUri(deviceTypeSvg(deviceType), "#000000")}")`;
}

export function recoloredDataUri(svgMarkup: string, hexColor: string): string {
  // Only fill="#141414" (the vendored glyph fill) is replaced; fill="none" on the root <svg>
  // is left untouched, matching every vendored icon's convention (see mapIcons.test.ts).
  const recolored = svgMarkup.replace(/fill="#141414"/g, `fill="${hexColor}"`);
  return `data:image/svg+xml;utf8,${encodeURIComponent(recolored)}`;
}

interface NodeVisual {
  image: string;
  color: {
    border: string;
    background: string;
    highlight: { border: string; background: string };
    hover: { border: string; background: string };
  };
  borderWidth: number;
  shapeProperties: { borderDashes: false | number[] };
}

// 13-UI-SPEC.md's accepted CRIT/UNREACH/DOWN tradeoff: same fill hex, differentiated by
// border weight/dash pattern instead (canvas-native styling Badge's variant system has no
// equivalent for).
const BORDER_STYLE: Record<string, { borderWidth: number; borderDashes: false | number[] }> = {
  DOWN: { borderWidth: 4, borderDashes: false },
  UNREACH: { borderWidth: 3, borderDashes: [4, 2] },
  CRIT: { borderWidth: 2, borderDashes: false },
  STALE: { borderWidth: 2, borderDashes: [2, 2] },
  OK: { borderWidth: 2, borderDashes: false },
  WARN: { borderWidth: 2, borderDashes: false },
  PEND: { borderWidth: 2, borderDashes: false },
  UNKNOWN: { borderWidth: 2, borderDashes: false },
};

// Cached by "${deviceType}|${state}" so a DataSet.update() of an unchanged node does not
// re-encode the same data URI on every poll cycle.
const nodeVisualCache = new Map<string, NodeVisual>();

export function nodeVisual(deviceType: string | null | undefined, state: string): NodeVisual {
  const cacheKey = `${deviceType}|${state}`;
  const cached = nodeVisualCache.get(cacheKey);
  if (cached) {
    return cached;
  }

  const hex = STATE_HEX[state] ?? STATE_HEX.UNKNOWN;
  const border = BORDER_STYLE[state] ?? BORDER_STYLE.UNKNOWN;
  const svg = deviceTypeSvg(deviceType);

  const visual: NodeVisual = {
    image: recoloredDataUri(svg, hex),
    color: {
      border: hex,
      background: "#ffffff",
      highlight: { border: "#1450f5", background: "#ffffff" },
      hover: { border: hex, background: "#ffffff" },
    },
    borderWidth: border.borderWidth,
    shapeProperties: { borderDashes: border.borderDashes },
  };

  nodeVisualCache.set(cacheKey, visual);
  return visual;
}
