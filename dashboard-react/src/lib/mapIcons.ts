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
  opacity?: number;
}

// DASH-15/14-UI-SPEC "Dimmed Consequence Treatment" and this plan's inferred-root decision:
// a consequence node of an open incident is de-emphasized (not hidden, no per-state alarm
// border), and an inferred (unmanaged-switch) root gets a distinct dashed warning border
// instead of borrowing the state palette's DOWN/UNREACH red (D-04: its own Checkmk state is
// UP -- it is simply unchecked, so a red border would assert something monitoring cannot see).
export type NodeEmphasis = "normal" | "dimmed" | "inferred-root";

const NEUTRAL_400 = "#96969f";
const WARN_HEX = "#f97316"; // STATE_HEX.WARN, matches the incident card's "warning" status

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

// Cached by "${deviceType}|${state}|${emphasis}" so a DataSet.update() of an unchanged node
// does not re-encode the same data URI on every poll cycle.
const nodeVisualCache = new Map<string, NodeVisual>();

export function nodeVisual(
  deviceType: string | null | undefined,
  state: string,
  emphasis: NodeEmphasis = "normal",
): NodeVisual {
  const cacheKey = `${deviceType}|${state}|${emphasis}`;
  const cached = nodeVisualCache.get(cacheKey);
  if (cached) {
    return cached;
  }

  const hex = STATE_HEX[state] ?? STATE_HEX.UNKNOWN;
  const border = BORDER_STYLE[state] ?? BORDER_STYLE.UNKNOWN;
  const svg = deviceTypeSvg(deviceType);

  // Same device-type/state image, faded and flattened to a neutral border -- "still there,
  // flagged as different", not hidden (UI-SPEC's Auto-Mode Design Decisions). An inferred
  // root's icon is recolored to the warning hue too, since its own Checkmk state is UP
  // (unchecked) -- the state-derived `hex` above would otherwise render it green.
  const image = emphasis === "inferred-root" ? recoloredDataUri(svg, WARN_HEX) : recoloredDataUri(svg, hex);
  const borderColor =
    emphasis === "dimmed" ? NEUTRAL_400 : emphasis === "inferred-root" ? WARN_HEX : hex;
  const borderWidth = emphasis === "dimmed" ? 2 : emphasis === "inferred-root" ? 3 : border.borderWidth;
  const borderDashes: false | number[] =
    emphasis === "dimmed" ? false : emphasis === "inferred-root" ? [6, 3] : border.borderDashes;

  const visual: NodeVisual = {
    image,
    color: {
      border: borderColor,
      background: "#ffffff",
      highlight: { border: "#1450f5", background: "#ffffff" },
      hover: { border: borderColor, background: "#ffffff" },
    },
    borderWidth,
    shapeProperties: { borderDashes },
    ...(emphasis === "dimmed" ? { opacity: 0.4 } : {}),
  };

  nodeVisualCache.set(cacheKey, visual);
  return visual;
}
