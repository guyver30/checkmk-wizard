// Per-site MQTT topic helpers. Every topic the poller publishes lives under
// `sites/<checkmkSite>/`, where the site id comes from /config.json at runtime (see
// runtimeConfig.ts). This module and store/mqttClient.ts are the only places that know about
// the prefix; the stores and components only ever see RELATIVE topics (e.g.
// "lan/devices/h1/status").
//
// The site id is NOT re-validated here: parseRuntimeConfig already restricts it to
// /^[A-Za-z][A-Za-z0-9_]{0,15}$/, so it cannot carry MQTT wildcards or separators.

import { ADMIN_TOPIC_ACK, ADMIN_TOPIC_FAKED } from "./adminMode";

export const RELATIVE_SUBSCRIBE_TOPICS = [
  "lan/devices/+/status",
  "lan/devices/+/services",
  "lan/devices/topology",
  "lan/events/recent",
  "lan/poller/status",
  "lan/incidents/+/status", // Phase 14 -- retained delivery on SUBACK gives every open incident
];

// Subscribed only on an admin page (?admin=1) whose wsadmin login loaded.
export const RELATIVE_ADMIN_SUBSCRIBE_TOPICS = [ADMIN_TOPIC_ACK, ADMIN_TOPIC_FAKED];

export function sitePrefix(site: string): string {
  return `sites/${site}/`;
}

export function siteTopic(site: string, relative: string): string {
  return `${sitePrefix(site)}${relative}`;
}

// Returns the relative topic, or null when the topic is not under this site's prefix. The
// trailing slash in the prefix is what keeps "sites/dmcx/..." from matching site "dmc".
export function stripSitePrefix(site: string, topic: string): string | null {
  const prefix = sitePrefix(site);
  return topic.startsWith(prefix) ? topic.slice(prefix.length) : null;
}

export function subscribeTopics(site: string, withAdmin: boolean): string[] {
  const relative = withAdmin
    ? [...RELATIVE_SUBSCRIBE_TOPICS, ...RELATIVE_ADMIN_SUBSCRIBE_TOPICS]
    : RELATIVE_SUBSCRIBE_TOPICS;
  return relative.map((topic) => siteTopic(site, topic));
}
