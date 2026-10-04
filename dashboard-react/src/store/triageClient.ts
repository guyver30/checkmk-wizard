// Publish-only MQTT connection for triage commands (D-21).
//
// Analog of mqttClient.ts, but deliberately separate: the main connection is a
// credential-fixed singleton (wsreader) with its own jittered backoff, and the triage login
// (wstriage) may write only `sites/<site>/needs/triage/cmd`, so reusing the read connection
// would either widen the read login or require reconnecting the whole dashboard. This
// connection is opened lazily on the first triage action, never subscribes, and does not
// auto-reconnect (reconnectPeriod 0): a failed publish resolves false and the user retries.

import mqtt, { type MqttClient } from "mqtt";
import { WS_PORT } from "../lib/config";
import { getRuntimeConfig } from "../lib/runtimeConfig";
import { siteTopic } from "../lib/topics";
import {
  TRIAGE_TOPIC_CMD,
  loadTriageConfig,
  type TriageCommand,
  type TriageConfig,
} from "../lib/triageMode";

export interface TriageDeps {
  connectFn?: typeof mqtt.connect;
  loadConfig?: () => Promise<TriageConfig | null>;
}

let client: MqttClient | null = null;
let opening: Promise<MqttClient | null> | null = null;

async function open(deps: TriageDeps): Promise<MqttClient | null> {
  const config = await (deps.loadConfig ?? loadTriageConfig)();
  if (!config) {
    return null;
  }
  const connectFn = deps.connectFn ?? mqtt.connect;
  const created = connectFn(`ws://${location.hostname}:${WS_PORT}`, {
    username: config.wsUsername,
    password: config.wsPassword,
    reconnectPeriod: 0,
    clean: true,
  });
  // An unhandled 'error' event can abort page initialization; never rethrow.
  created.on("error", (err) => {
    console.error("MQTT triage error", err);
  });
  created.on("close", () => {
    if (client === created) {
      client = null;
    }
  });
  return created;
}

// Resolves true once the broker acknowledged the publish (QoS 1), false when the login is
// unavailable or the publish failed. Never retained: a retained command would replay.
export async function publishTriage(
  cmd: TriageCommand,
  deps: TriageDeps = {},
): Promise<boolean> {
  try {
    if (!client) {
      opening ??= open(deps).finally(() => {
        opening = null;
      });
      client = await opening;
      if (!client) {
        return false;
      }
    }
    const active = client;
    const topic = siteTopic(getRuntimeConfig().checkmkSite, TRIAGE_TOPIC_CMD);
    return await new Promise<boolean>((resolve) => {
      active.publish(topic, JSON.stringify(cmd), { qos: 1, retain: false }, (err) => {
        resolve(!err);
      });
    });
  } catch {
    return false;
  }
}

// Test-only: drops the module-level connection so each test starts clean.
export function __resetForTests(): void {
  client = null;
  opening = null;
}
