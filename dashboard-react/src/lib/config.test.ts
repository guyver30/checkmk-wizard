import { describe, expect, it } from "vitest";
import {
  isSecretConfigured,
  isTopologyEditingConfigured,
  TOPOLOGY_EDITOR_SECRET,
  TOPOLOGY_EDITOR_SECRET_PLACEHOLDER,
} from "./config";

describe("isSecretConfigured", () => {
  it("is false when the value equals the placeholder", () => {
    expect(isSecretConfigured("<TOPOLOGY_EDITOR_SECRET>")).toBe(false);
  });

  it("is true for any other value", () => {
    expect(isSecretConfigured("a-real-secret")).toBe(true);
  });
});

describe("isTopologyEditingConfigured", () => {
  it("is false while TOPOLOGY_EDITOR_SECRET is still the shipped placeholder", () => {
    expect(TOPOLOGY_EDITOR_SECRET).toBe(TOPOLOGY_EDITOR_SECRET_PLACEHOLDER);
    expect(isTopologyEditingConfigured()).toBe(false);
  });
});
