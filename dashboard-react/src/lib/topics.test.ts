import { describe, expect, it } from "vitest";
import {
  RELATIVE_SUBSCRIBE_TOPICS,
  siteTopic,
  sitePrefix,
  stripSitePrefix,
  subscribeTopics,
} from "./topics";

describe("sitePrefix / siteTopic", () => {
  it("builds the per-site prefix and topics", () => {
    expect(sitePrefix("dmc")).toBe("sites/dmc/");
    expect(siteTopic("dmc", "admin/cmd")).toBe("sites/dmc/admin/cmd");
  });
});

describe("stripSitePrefix", () => {
  it("returns the relative topic for this site", () => {
    expect(stripSitePrefix("dmc", "sites/dmc/lan/devices/h1/status")).toBe("lan/devices/h1/status");
  });

  it("returns null for the legacy unprefixed namespace", () => {
    expect(stripSitePrefix("dmc", "lan/devices/h1/status")).toBeNull();
  });

  it("returns null for another site, including one that shares a name prefix", () => {
    expect(stripSitePrefix("dmc", "sites/other/lan/poller/status")).toBeNull();
    expect(stripSitePrefix("dmc", "sites/dmcx/lan/poller/status")).toBeNull();
  });
});

describe("subscribeTopics", () => {
  it("lists the old topics plus the three analytics topics", () => {
    expect(RELATIVE_SUBSCRIBE_TOPICS).toEqual([
      "lan/devices/+/status",
      "lan/devices/+/services",
      "lan/devices/topology",
      "lan/events/recent",
      "lan/poller/status",
      "lan/incidents/+/status",
      "lan/needs/+/status",
      "lan/forecasts/+",
      "lan/incidents/+/narration",
    ]);
  });

  it("prefixes the 9 lan topics in order outside admin mode", () => {
    const topics = subscribeTopics("dmc", false);
    expect(topics).toHaveLength(9);
    expect(topics).toEqual(RELATIVE_SUBSCRIBE_TOPICS.map((t) => `sites/dmc/${t}`));
  });

  it("appends the admin ack and faked topics in admin mode", () => {
    const topics = subscribeTopics("dmc", true);
    expect(topics.slice(-2)).toEqual(["sites/dmc/admin/ack", "sites/dmc/admin/faked"]);
    expect(topics).toHaveLength(11);
  });

  it("never subscribes across sites", () => {
    for (const topic of subscribeTopics("dmc", true)) {
      expect(topic.startsWith("sites/dmc/")).toBe(true);
      expect(topic).not.toContain("sites/+");
      expect(topic).not.toContain("#");
    }
  });
});
