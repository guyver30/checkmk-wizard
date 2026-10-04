// Triage commands (D-21): the sixth lib module allowed to do network I/O (only
// loadTriageConfig), after runtimeConfig.ts, checkmkWrite.ts, mqttClient.ts, adminMode.ts and
// historyClient.ts. Modelled on adminMode.ts: a config fetch that never rejects, plus a pure
// command builder. It never imports a store.
//
// GET /triage-config.json returns the wstriage login, which the broker allows to write only
// `sites/<site>/needs/triage/cmd`. It is fetched lazily by store/triageClient.ts on the first
// triage action, never at page load.

import { newCommandId } from "./adminMode";

// RELATIVE topic; triageClient.ts prefixes it with `sites/<checkmkSite>/` on the wire.
export const TRIAGE_TOPIC_CMD = "needs/triage/cmd";
export const TRIAGE_NOTE_MAX = 200;
export const TRIAGE_BY_MAX = 64;

export type TriageAction = "downgrade" | "upgrade" | "cancel";

export interface TriageCommand {
  id: string;
  need_id: string;
  action: TriageAction;
  note?: string;
  by?: string;
}

export interface TriageConfig {
  wsUsername: string;
  wsPassword: string;
}

export function buildTriageCommand(
  needId: string,
  action: TriageAction,
  note?: string,
  by?: string,
  id: string = newCommandId(),
): TriageCommand {
  const cmd: TriageCommand = { id, need_id: needId, action };
  const cleanNote = (note ?? "").trim().slice(0, TRIAGE_NOTE_MAX);
  const cleanBy = (by ?? "").trim().slice(0, TRIAGE_BY_MAX);
  if (cleanNote !== "") {
    cmd.note = cleanNote;
  }
  if (cleanBy !== "") {
    cmd.by = cleanBy;
  }
  return cmd;
}

export function parseTriageConfig(raw: unknown): TriageConfig | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return null;
  }
  const { wsUsername, wsPassword } = raw as Record<string, unknown>;
  if (
    typeof wsUsername !== "string" ||
    wsUsername === "" ||
    typeof wsPassword !== "string" ||
    wsPassword === ""
  ) {
    return null;
  }
  return { wsUsername, wsPassword };
}

// Never rejects: 404, network error, timeout or bad JSON all resolve null.
export async function loadTriageConfig(
  fetchFn: typeof fetch = fetch,
): Promise<TriageConfig | null> {
  try {
    const response = await fetchFn("/triage-config.json", {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) {
      return null;
    }
    return parseTriageConfig(await response.json());
  } catch {
    return null;
  }
}
