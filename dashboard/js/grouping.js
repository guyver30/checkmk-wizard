// Group membership, worst-of roll-up and the stale-never-masks-known-bad rule (D-05, D-06,
// D-07, D-15, D-16). Calls isDeviceStale() (staleness.js) and effectiveState() (display.js)
// as globals -- this module does not redefine them.
//
// No DOM access, no broker connection, no browser storage, no network calls -- pure
// functions only. Persisting the D-05 grouping-mode choice in browser storage is the
// shell's job (plan 11-06); this module only takes `mode` as an argument.

// Mirrors compute_overall_state()'s worst-of ordering in scripts/mqtt_poller.py (host
// DOWN/UNREACHABLE always wins outright, then CRIT > UNKNOWN > WARN > OK). The two tables
// live in different languages and must be kept in step by hand -- there is no shared
// source of truth between Python and this file.
const SEVERITY_RANK = { OK: 0, PEND: 0, WARN: 1, UNKNOWN: 2, CRIT: 3, UNREACH: 3, DOWN: 4 };

function groupKeyFor(devicePayload, mode) {
  if (!devicePayload || typeof devicePayload !== "object") {
    return mode === "folder" ? "(no folder)" : "untyped";
  }
  if (mode === "folder") {
    const folder = typeof devicePayload.folder === "string" ? devicePayload.folder.trim() : "";
    return folder || "(no folder)";
  }
  // "device_type" is the default mode (D-05). "unknown" collapses to a single literal
  // "untyped" group, per D-16's degrade-type-grouping rule -- the tag group being absent
  // site-wide is a site-configuration signal, not a real category to group by.
  const deviceType = devicePayload.device_type;
  if (!deviceType || deviceType === "unknown") {
    return "untyped";
  }
  return deviceType;
}

function buildGroupIndex(devicesMap, mode) {
  // Built once per topology/mode change rather than recomputed per incoming status
  // message (Pitfall 5, 11-RESEARCH.md): recomputing group membership by filtering the
  // whole devices map on every single-device update is O(fleet) per message, which is
  // harmless at today's ~21 hosts but the wrong shape before Phases 12/13 grow both fleet
  // size and update frequency on the same store. Callers should rebuild this index only
  // when the topology topic or the grouping mode changes, and reuse it across per-device
  // status messages in between.
  const index = new Map();
  if (!devicesMap || typeof devicesMap.forEach !== "function") {
    return index;
  }
  devicesMap.forEach((device, id) => {
    const key = groupKeyFor(device, mode);
    if (!index.has(key)) {
      index.set(key, new Set());
    }
    index.get(key).add(id);
  });
  return index;
}

function rollUpGroup(deviceIds, devicesMap, nowMs = Date.now()) {
  let worst = "OK";
  let worstRank = 0;
  let nonOkCount = 0;
  let total = 0;
  let hatched = false;

  const ids = deviceIds && typeof deviceIds[Symbol.iterator] === "function" ? deviceIds : [];
  for (const id of ids) {
    const device = devicesMap && typeof devicesMap.get === "function" ? devicesMap.get(id) : undefined;
    if (!device) {
      continue;
    }
    total += 1;
    if (isDeviceStale(device, nowMs)) {
      // D-15: stale never masks a known-bad child -- excluded from the worst-of
      // computation and from nonOkCount, but still marks the group hatched so both facts
      // (worst known state AND partial blindness) render simultaneously.
      hatched = true;
      continue;
    }
    // Read the derived state, never the raw `state` key, so UNREACH ranks correctly
    // (Pitfall 6) instead of being silently folded into DOWN.
    const state = effectiveState(device);
    const rank = SEVERITY_RANK[state] ?? SEVERITY_RANK.UNKNOWN;
    if (rank > worstRank) {
      worst = state;
      worstRank = rank;
    }
    if (state !== "OK" && state !== "PEND") {
      nonOkCount += 1;
    }
  }

  return { worst, worstRank, nonOkCount, total, hatched };
}

function sortedGroupKeys(groupIndex) {
  // A stable alphabetical display order so the tree and the overview cannot disagree
  // about ordering between re-renders.
  if (!groupIndex || typeof groupIndex.keys !== "function") {
    return [];
  }
  return [...groupIndex.keys()].sort((a, b) => a.localeCompare(b));
}
