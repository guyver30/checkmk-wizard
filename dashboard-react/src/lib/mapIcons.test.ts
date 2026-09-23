import { describe, expect, it } from "vitest";
import { STATE_HEX, deviceTypeSvg, recoloredDataUri, nodeVisual } from "./mapIcons";

describe("STATE_HEX", () => {
  it("has the exact eight state hex values from 13-UI-SPEC.md's State palette table", () => {
    expect(STATE_HEX.OK).toBe("#22c55e");
    expect(STATE_HEX.WARN).toBe("#f97316");
    expect(STATE_HEX.CRIT).toBe("#e5252a");
    expect(STATE_HEX.UNREACH).toBe("#e5252a");
    expect(STATE_HEX.DOWN).toBe("#e5252a");
    expect(STATE_HEX.UNKNOWN).toBe("#111114");
    expect(STATE_HEX.PEND).toBe("#55555f");
    expect(STATE_HEX.STALE).toBe("#55555f");
  });
});

describe("deviceTypeSvg", () => {
  it("maps NetworkDevice to the internet.svg markup", () => {
    expect(deviceTypeSvg("NetworkDevice")).toContain("15.1001 7.9");
  });

  it("maps E-link to the api.svg markup", () => {
    const apiMarkup = deviceTypeSvg("E-link");
    const networkMarkup = deviceTypeSvg("NetworkDevice");
    expect(apiMarkup).not.toBe(networkMarkup);
    expect(apiMarkup).toContain("fill=\"#141414\"");
  });

  it("falls back to circle.svg for undefined, 'unknown', and an unrecognized value, never throwing", () => {
    const circleMarkup = deviceTypeSvg("circle-marker-does-not-exist-as-key");
    expect(() => deviceTypeSvg(undefined)).not.toThrow();
    expect(deviceTypeSvg(undefined)).toBe(deviceTypeSvg("nonsense"));
    expect(deviceTypeSvg("unknown")).toBe(deviceTypeSvg(undefined));
    expect(deviceTypeSvg("nonsense")).toBe(circleMarkup);
  });
});

describe("recoloredDataUri", () => {
  const svg = '<svg fill="none"><path fill="#141414" d="M0 0"/></svg>';

  it("starts with the data:image/svg+xml;utf8, prefix", () => {
    expect(recoloredDataUri(svg, "#22c55e")).toMatch(/^data:image\/svg\+xml;utf8,/);
  });

  it("decodes to contain the new fill and no trace of the original fill", () => {
    const uri = recoloredDataUri(svg, "#22c55e");
    const decoded = decodeURIComponent(uri.replace(/^data:image\/svg\+xml;utf8,/, ""));
    expect(decoded).toContain('fill="#22c55e"');
    expect(decoded).not.toContain('fill="#141414"');
  });

  it("leaves fill=\"none\" untouched", () => {
    const uri = recoloredDataUri(svg, "#22c55e");
    const decoded = decodeURIComponent(uri.replace(/^data:image\/svg\+xml;utf8,/, ""));
    expect(decoded).toContain('fill="none"');
  });
});

describe("nodeVisual", () => {
  it("DOWN has borderWidth 4 with borderDashes false", () => {
    const visual = nodeVisual("NetworkDevice", "DOWN");
    expect(visual.borderWidth).toBe(4);
    expect(visual.shapeProperties.borderDashes).toBe(false);
  });

  it("UNREACH has borderWidth 3 and borderDashes [4,2]", () => {
    const visual = nodeVisual("NetworkDevice", "UNREACH");
    expect(visual.borderWidth).toBe(3);
    expect(visual.shapeProperties.borderDashes).toEqual([4, 2]);
  });

  it("CRIT has 2/false", () => {
    const visual = nodeVisual("NetworkDevice", "CRIT");
    expect(visual.borderWidth).toBe(2);
    expect(visual.shapeProperties.borderDashes).toBe(false);
  });

  it("STALE has 2/[2,2]", () => {
    const visual = nodeVisual("NetworkDevice", "STALE");
    expect(visual.borderWidth).toBe(2);
    expect(visual.shapeProperties.borderDashes).toEqual([2, 2]);
  });

  it("OK/WARN/PEND/UNKNOWN have 2/false", () => {
    for (const state of ["OK", "WARN", "PEND", "UNKNOWN"]) {
      const visual = nodeVisual("NetworkDevice", state);
      expect(visual.borderWidth).toBe(2);
      expect(visual.shapeProperties.borderDashes).toBe(false);
    }
  });

  it("color.border equals the state hex and color.highlight.border is the accent blue", () => {
    const visual = nodeVisual("NetworkDevice", "WARN");
    expect(visual.color.border).toBe(STATE_HEX.WARN);
    expect(visual.color.highlight.border).toBe("#1450f5");
  });

  it("falls back to UNKNOWN styling for an unrecognised state", () => {
    const visual = nodeVisual("NetworkDevice", "bogus-state");
    const unknownVisual = nodeVisual("NetworkDevice", "UNKNOWN");
    expect(visual.borderWidth).toBe(unknownVisual.borderWidth);
    expect(visual.shapeProperties.borderDashes).toEqual(unknownVisual.shapeProperties.borderDashes);
    expect(visual.color.border).toBe(unknownVisual.color.border);
  });

  it("sets image, background, and hover colors as specified", () => {
    const visual = nodeVisual("NetworkDevice", "OK");
    expect(visual.image).toMatch(/^data:image\/svg\+xml;utf8,/);
    expect(visual.color.background).toBe("#ffffff");
    expect(visual.color.highlight.background).toBe("#ffffff");
    expect(visual.color.hover.border).toBe(STATE_HEX.OK);
    expect(visual.color.hover.background).toBe("#ffffff");
  });
});
