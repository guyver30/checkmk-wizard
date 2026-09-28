import { describe, expect, it } from "vitest";
import { hostHref, incidentHref, withSearchParam } from "./searchLinks";

describe("withSearchParam", () => {
  it("sets a key on top of an existing query string, keeping the other param", () => {
    const href = withSearchParam("?incident=i1", "host", "web 1");
    const url = new URL(href, "http://example.test");
    expect(url.searchParams.get("host")).toBe("web 1");
    expect(url.searchParams.get("incident")).toBe("i1");
  });

  it("deletes the key when value is null, keeping any other param", () => {
    expect(withSearchParam("?incident=i1&host=a", "host", null)).toBe("/?incident=i1");
  });

  it("returns '/' when deleting the only param leaves an empty query", () => {
    expect(withSearchParam("?host=a", "host", null)).toBe("/");
  });
});

describe("hostHref / incidentHref", () => {
  it("hostHref sets host and keeps an existing incident", () => {
    const href = hostHref("?incident=i1", "web1");
    const url = new URL(href, "http://example.test");
    expect(url.searchParams.get("host")).toBe("web1");
    expect(url.searchParams.get("incident")).toBe("i1");
  });

  it("incidentHref sets incident and keeps an existing host", () => {
    const href = incidentHref("?host=web1", "i1");
    const url = new URL(href, "http://example.test");
    expect(url.searchParams.get("incident")).toBe("i1");
    expect(url.searchParams.get("host")).toBe("web1");
  });
});
