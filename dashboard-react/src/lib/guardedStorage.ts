// localStorage access THROWS (it does not return null) when site data is blocked -- a
// browser with site data blocked, a private window, or an embedded frame with restricted
// storage all raise on access. D-26 makes the in-memory value the source of truth for the
// session: storage is only how a value survives a reload, and a refused read or write must
// never break the interaction. This is the same rule dashboard/js/render-shell.js's
// groupingModeOverride fix established in Phase 11 (see groupingMode()'s try/catch around
// localStorage.getItem), ported here for the React app.

export function readJson<T>(key: string, fallback: T): T {
  let raw: string | null;
  try {
    raw = localStorage.getItem(key);
  } catch {
    return fallback;
  }
  if (raw === null) {
    return fallback;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export function writeJson(key: string, value: unknown): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
