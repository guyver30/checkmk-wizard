import { describe, expect, it } from "vitest";
import { middleTruncate } from "./truncate";

describe("middleTruncate", () => {
  it("returns the string unchanged when already within budget", () => {
    expect(middleTruncate("192.168.0.213", 20)).toBe("192.168.0.213");
  });

  it("truncates to exactly the budget, keeping the head prefix and the distinguishing tail", () => {
    const result = middleTruncate("192.168.0.213", 10);
    expect(result).toHaveLength(10);
    expect(result.startsWith("192")).toBe(true);
    expect(result.endsWith("213")).toBe(true);
  });

  it("inserts a single ellipsis character, never three periods", () => {
    const result = middleTruncate("192.168.0.213", 10);
    expect(result).toContain("…");
    expect(result).not.toContain("...");
    expect(result.match(/…/g)).toHaveLength(1);
  });

  it("returns an empty string for empty input", () => {
    expect(middleTruncate("", 10)).toBe("");
  });

  it("returns an empty string for non-string input without throwing", () => {
    expect(() => middleTruncate(null as unknown as string, 10)).not.toThrow();
    expect(middleTruncate(null as unknown as string, 10)).toBe("");
  });

  it("never returns a string longer than the budget, across several budgets", () => {
    const value = "192.168.0.213";
    for (const budget of [0, 1, 2, 3, 5, 8, 10, 13, 20]) {
      expect(middleTruncate(value, budget).length).toBeLessThanOrEqual(budget);
    }
  });

  it("produces different truncated strings for two hosts sharing a long common prefix and differing only in the tail", () => {
    const a = middleTruncate("192.168.0.21", 10);
    const b = middleTruncate("192.168.0.213", 10);
    expect(a).not.toBe(b);
  });
});
