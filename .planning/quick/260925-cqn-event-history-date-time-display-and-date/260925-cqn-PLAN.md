---
phase: quick-260925-cqn
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - dashboard-react/src/lib/display.ts
  - dashboard-react/src/lib/display.test.ts
  - dashboard-react/src/lib/eventFilter.ts
  - dashboard-react/src/lib/eventFilter.test.ts
  - dashboard-react/src/components/EventRow.tsx
  - dashboard-react/src/components/EventHistory.tsx
  - dashboard-react/src/components/EventHistory.test.tsx
  - scripts/mqtt_poller.py
  - tests/test_mqtt_poller.py
  - deploy/compose.yaml
  - dashboard-react/README.md
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
autonomous: true
requirements: [QUICK-260925-cqn]

must_haves:
  truths:
    - "Every event row in the dashboard's event history shows the event's full local date and time (YYYY-MM-DD HH:MM:SS), not just HH:MM"
    - "The operator can set a From and/or To date-time above the event list and only events inside that inclusive range are shown, still newest-first"
    - "A Clear control resets both bounds and restores the full list"
    - "When events exist but none fall in the range, the pane says 'No events in this range' (distinct from 'No recent events' when the feed is empty)"
    - "A reversed range (From after To) shows an inline error and does not filter; an empty bound is treated as open-ended"
    - "The poller keeps up to 1000 events in lan/events/recent by default and in the shipped compose file"
  artifacts:
    - path: "dashboard-react/src/lib/eventFilter.ts"
      provides: "Pure range-filter helper over EventEntry[]"
      exports: ["filterEventsByRange", "parseRangeBound"]
    - path: "dashboard-react/src/lib/display.ts"
      provides: "formatDateTime(iso) local date+time formatter"
      contains: "export function formatDateTime"
    - path: "scripts/mqtt_poller.py"
      contains: "DEFAULT_EVENTS_MAX_ENTRIES = 1000"
    - path: "deploy/compose.yaml"
      contains: "EVENTS_MAX_ENTRIES=1000"
  key_links:
    - from: "dashboard-react/src/components/EventRow.tsx"
      to: "formatDateTime"
      via: "import from ../lib/display"
      pattern: "formatDateTime\\(entry\\?\\.timestamp\\)"
    - from: "dashboard-react/src/components/EventHistory.tsx"
      to: "filterEventsByRange"
      via: "applied to events.slice().reverse() rows (single reversal kept)"
      pattern: "filterEventsByRange"
---

<objective>
Show full local date + time on every event-history row, add a client-side From/To date-time range filter above the list, and raise the events feed cap from 50 to 1000 (operator decision 2026-09-25) so the filter has days of history to work with.

Purpose: the dashboard's event pane currently shows only HH:MM, so events from different days are indistinguishable, and only 50 events are kept.
Output: new `formatDateTime` + `eventFilter.ts` helpers with vitest coverage, an updated EventRow/EventHistory, cap raised in the poller/compose/tests, a written payload-size/limits verification note in the SUMMARY, and updated docs.
</objective>

<execution_context>
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/workflows/execute-plan.md
@/home/kone/.claude/plugins/cache/buildomator/bm/4.9.1/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@dashboard-react/src/components/EventHistory.tsx
@dashboard-react/src/components/EventRow.tsx
@dashboard-react/src/components/EventHistory.test.tsx
@dashboard-react/src/lib/display.ts
@dashboard-react/src/components/GroupingControls.test.tsx

Repo rules: uv only for Python (`uv run`, `uvx`), surgical changes, update docs after the change, and keep the "why" comment style (cite what was verified and how).

<interfaces>
From dashboard-react/src/lib/types.ts:
  export interface EventEntry { device_id?: string; state?: string; timestamp?: string; from?: string | null; to?: string | null; [key: string]: unknown; }

From dashboard-react/src/lib/display.ts (line ~105):
  export function formatClock(isoString: string | null | undefined): string  // "HH:MM" local, "unknown" on unparseable
  // Also used by src/routes/DetailsRoute.tsx:217 (per-device history) and the D-14 banner. DO NOT change formatClock.

From kone-design-system (node_modules/kone-design-system/dist/index.d.ts):
  Input: forwardRef<HTMLInputElement, Omit<InputHTMLAttributes,"size"> & { label?: ReactNode; hint?: ReactNode; error?: string; size?: "xs"|"sm"|"md"; onClear?: () => void }>
  Button: forwardRef<HTMLButtonElement, ButtonHTMLAttributes & { variant?: "primary"|"secondary"|"tertiary"|"destructive"|"neutral"; size?: "sm"|"md"|"lg"; loading?: boolean }>
  (DatePicker exists but is date-only and its own doc says "prefer the browser default input where possible" -- use Input type="datetime-local" instead.)

Poller event timestamps: scripts/mqtt_poller.py line ~1189 `datetime.datetime.now(datetime.UTC).isoformat()` -> e.g. "2026-09-25T06:12:34.123456+00:00". Each entry is {timestamp, device_id, event, from, to}; run_cycle() line ~1819 truncates with `[-config.events_max_entries:]` and publishes retained QoS1 on lan/events/recent.

EventHistory is mounted in src/routes/IndexRoute.tsx:214 as `centreBottom={<EventHistory />}` -- the root must stay a full-height flex column.

Pinning Date in tests (from GroupingControls.test.tsx): `vi.useFakeTimers({ toFake: ["Date"] }); vi.setSystemTime(NOW_MS);` in beforeEach, `vi.useRealTimers()` in afterEach.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Pure helpers -- formatDateTime and eventFilter (with tests)</name>
  <files>dashboard-react/src/lib/display.ts, dashboard-react/src/lib/display.test.ts, dashboard-react/src/lib/eventFilter.ts, dashboard-react/src/lib/eventFilter.test.ts</files>
  <behavior>
    - formatDateTime(valid ISO) returns local "YYYY-MM-DD HH:MM:SS" (zero-padded, 24h); tests compute the expected string from `new Date(iso)` local getters so they pass in any TZ, and also assert the regex /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.
    - formatDateTime(undefined | null | "" | "not-a-date") returns "unknown" (same sentinel as formatClock).
    - parseRangeBound("") / undefined returns null (open bound); parseRangeBound("2026-09-24T10:30") returns the local-time epoch ms (Date.parse of an offset-less datetime-local string is local time per ECMAScript); garbage returns null.
    - filterEventsByRange(rows, {from, to}) with both null returns the same rows (content-equal, in the same order) and status "unfiltered".
    - From-only keeps entries with timestamp >= from; To-only keeps entries with timestamp <= end of the To minute (to + 59_999 ms, because datetime-local has minute granularity and "To 10:30" must include 10:30:45); both bounds inclusive.
    - When any bound is active, entries that are null or whose timestamp is missing/unparseable are excluded.
    - from > to (after the +59_999 adjustment, i.e. From strictly later than the To minute) returns rows unfiltered with status "reversed".
    - Result order is preserved exactly (input already newest-first); the input array is not mutated (assert with a frozen array via Object.freeze).
    - Status "filtered" when a valid range is applied (even if it yields zero rows).
  </behavior>
  <action>
    In display.ts add `export function formatDateTime(isoString: string | null | undefined): string` next to formatClock, same parse/"unknown" pattern, output local `YYYY-MM-DD HH:MM:SS` (ISO-like order is unambiguous across locales, unlike toLocaleString's D/M vs M/D; local time matches formatClock's existing choice). Add a short why-comment. Leave formatClock untouched (DetailsRoute and the D-14 banner depend on HH:MM).

    Create src/lib/eventFilter.ts exporting: `type EventRange = { from: number | null; to: number | null }`, `type EventFilterStatus = "unfiltered" | "filtered" | "reversed"`, `parseRangeBound(value: string | undefined): number | null`, and `filterEventsByRange<T extends EventEntry | null | undefined>(rows: readonly T[], range: EventRange): { rows: T[]; status: EventFilterStatus }`. Implement with `rows.filter(...)` (never sort/reverse/splice -- ordering is owned by EventHistory's single slice().reverse()). Document the inclusive-to-end-of-minute decision and the "reversed range = don't filter, caller shows an error" decision in a header comment. No dependency on "now", so no fake timers are needed here; if the executor adds any now-relative test, pin Date per the GroupingControls pattern.

    Write display.test.ts additions (new describe "formatDateTime") and new eventFilter.test.ts covering every behavior bullet. Run RED first, then implement to GREEN.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard/dashboard-react && npx vitest run src/lib/display.test.ts src/lib/eventFilter.test.ts</automated>
  </verify>
  <done>Both test files pass; formatClock tests unchanged and still passing; eventFilter.ts exports the four names above.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: EventRow date+time and EventHistory range filter UI (with tests)</name>
  <files>dashboard-react/src/components/EventRow.tsx, dashboard-react/src/components/EventHistory.tsx, dashboard-react/src/components/EventHistory.test.tsx</files>
  <behavior>
    - Each rendered row shows formatDateTime(entry.timestamp) (assert via the same local-getter expected string as Task 1), and the time element is a `<time dateTime={raw ISO}>` so the raw value is machine-readable.
    - Existing tests still pass unchanged: newest-first order c,b,a; store array not mutated; "No recent events" for empty array; raw device_id fallback; null entry tolerated.
    - Filter bar renders labelled inputs "From" and "To" (getByLabelText(/from/i), getByLabelText(/to/i)) of type datetime-local, plus a "Clear" button.
    - Setting From (fireEvent.change with a local "YYYY-MM-DDTHH:MM" value built from the fixture timestamps via local getters, so TZ-independent) hides older rows and keeps newest-first order.
    - A range excluding every event shows "No events in this range" and NOT "No recent events"; the log region is still present.
    - From later than To shows an inline error on the To input (text like "End must be after start") and all rows remain visible.
    - Clear empties both inputs and restores all rows; Clear is disabled when both inputs are empty.
    - With an empty store array, "No recent events" is shown (filter bar may render; the existing message wins over the range message).
    - Store array still not mutated after filtering (extend the existing mutation test or add one).
  </behavior>
  <action>
    EventRow.tsx: replace the formatClock import/use with formatDateTime; wrap the text in `<time dateTime={entry?.timestamp ?? undefined}>` keeping the existing span classes (shrink-0 font-mono text-xs text-fg-tertiary); update the header comment ("time" -> "date+time"). No other layout changes.

    EventHistory.tsx: hold `fromValue`/`toValue` strings in useState (raw datetime-local input values). Restructure to an outer `flex h-full flex-col` wrapper containing (1) a shrink-0 filter bar: two kone-design-system `Input` components with `type="datetime-local"`, `size="sm"`, `label="From"`/`label="To"`, distinct ids, and `error` on To when status is "reversed"; plus a kone `Button variant="tertiary" size="sm"` labelled "Clear" that resets both strings, disabled when both are empty; use existing design-system spacing tokens/Tailwind classes consistent with the file (gap-2, p-3, etc.); and (2) the existing `role="log" aria-label="Recent events" aria-live="polite"` region as `flex-1 overflow-auto`. Keep the filter controls OUTSIDE the aria-live log so typing in them isn't announced as log updates.

    Row computation: keep the load-bearing comment and the single `events.slice().reverse()` exactly once, then pass that result into `filterEventsByRange(rows, { from: parseRangeBound(fromValue), to: parseRangeBound(toValue) })`. Do not add another reverse or sort. Empty states inside the log region: events.length === 0 -> existing NO_EVENTS_TEXT; else filtered rows empty -> new const NO_EVENTS_IN_RANGE_TEXT = "No events in this range". Keep the composite key logic. Note in a comment that 1000 is the new cap, so the list can be up to 1000 rows (plain rendering is fine at that size; no virtualisation added).

    Extend EventHistory.test.tsx with the behaviors above using fireEvent from @testing-library/react (check what the file already imports; match it). Build datetime-local strings from fixture Dates via local getters so tests are TZ-independent. None of these depend on "now"; if any does, pin with vi.useFakeTimers({ toFake: ["Date"] }) + vi.setSystemTime per GroupingControls.test.tsx.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard/dashboard-react && npm run typecheck && npm test && npm run build</automated>
  </verify>
  <done>typecheck clean, full vitest suite passes (319 existing + new), production build succeeds; EventHistory contains exactly one `.reverse()` (grep -c "reverse()" on non-comment lines == 1).</done>
</task>

<task type="auto">
  <name>Task 3: Raise events cap to 1000, verify transport limits, update docs</name>
  <files>scripts/mqtt_poller.py, tests/test_mqtt_poller.py, deploy/compose.yaml, dashboard-react/README.md, docs/Podman setup for checkmk, minio, mosquitto, worker.md</files>
  <action>
    Per operator decision 2026-09-25: set `DEFAULT_EVENTS_MAX_ENTRIES = 1000` (scripts/mqtt_poller.py line ~60) with a one-line dated comment citing the decision and the date-range filter; set `EVENTS_MAX_ENTRIES=1000` in deploy/compose.yaml (line ~189); change `assert config.events_max_entries == 50` to 1000 in tests/test_mqtt_poller.py (~line 314). Then `grep -rn "EVENTS_MAX_ENTRIES\|events_max_entries" scripts tests deploy docs dashboard-react/src dashboard-react/README.md` and fix any other place asserting/documenting 50 (ignore docs/mockup/ -- legacy preview harness). Do not touch HISTORY_MAX_ENTRIES.

    Verification of transport limits -- record results in the SUMMARY under a "Payload / limits verification" heading, labelling each item VERIFIED (with the command/file:line evidence) or ASSUMED:
    (a) Payload size: write a throwaway script in the session scratchpad (not the repo) run via `uv run` that builds 1000 entries shaped exactly like run_cycle()'s events (real isoformat timestamp, a long realistic device_id e.g. 40 chars, event "state_change", from/to states) and serialises them the same way `_publish_json` does (read `_publish_json` in scripts/mqtt_poller.py to match separators/encoding); report the byte count (expected roughly 130-180 KB).
    (b) Mosquitto: confirm deploy/mosquitto.conf sets neither `max_packet_size` nor `message_size_limit`, and cite the mosquitto.conf(5) defaults (use context7 or the man page: max_packet_size default 0 = no broker limit beyond the MQTT protocol max of ~256 MB; message_size_limit deprecated, default 0 = unlimited). Also note whether mosquitto.conf sets `websockets_*` buffer options (it does not) and what libwebsockets fragmenting implies (mosquitto handles fragmented frames).
    (c) Dashboard client: confirm dashboard-react/src/store/mqttClient.ts passes no `maxPacketSize` to mqtt.connect (lines ~79-84), and grep node_modules/mqtt and node_modules/mqtt-packet for `maxPacketSize` to confirm the default is unset/unlimited for incoming packets in mqtt 5.16.0 (cite file:line). The browser connects directly to mosquitto's WS listener (`ws://${location.hostname}:${WS_PORT}`, host port 9002), not through nginx, so no nginx proxy buffer applies -- state this with evidence.
    (d) Anything not live-tested (e.g. an actual publish of the 1000-entry array through a running broker to a browser) must be listed as ASSUMED. Optionally, if `podman ps` shows the mosquitto container running, publish the generated payload to a scratch topic (NOT lan/events/recent) with mosquitto_pub/-sub -C 1 and compare byte counts, then clear the scratch retained message; otherwise skip and mark ASSUMED.

    Docs: update the Podman doc topic-contract row for `lan/events/recent` (~line 358) to state the default cap is 1000 (`EVENTS_MAX_ENTRIES`, default 1000) and approximate payload size; if a nearby section lists poller env defaults, update it too. In dashboard-react/README.md add a short "Event history" section describing: date+time rows (local time, YYYY-MM-DD HH:MM:SS), the From/To filter (inclusive, To includes its whole minute, reversed range shows an error and leaves the list unfiltered, Clear resets), client-side only over the retained `lan/events/recent` array, and the 1000-entry cap set by the poller's EVENTS_MAX_ENTRIES. Also correct README line 64 if it is misleading (`HISTORY_MAX_ENTRIES` bounds the per-device history list, not the global event feed) -- only if src/lib/config.ts confirms that.
  </action>
  <verify>
    <automated>cd /home/kone/checkmk-wizard && uv run pytest tests/test_mqtt_poller.py -q && uvx ruff check --no-cache; grep -n "DEFAULT_EVENTS_MAX_ENTRIES = 1000" scripts/mqtt_poller.py && grep -n "EVENTS_MAX_ENTRIES=1000" deploy/compose.yaml</automated>
  </verify>
  <done>pytest passes; ruff reports the same 7 pre-existing findings and no new ones; both greps match; docs updated; SUMMARY contains the VERIFIED/ASSUMED payload-limits list with the measured byte count.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| broker -> browser | Retained lan/events/recent JSON (poller-authored) parsed by the dashboard |
| operator -> filter inputs | Local datetime-local strings typed into the UI |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-cqn-01 | Tampering | eventFilter.ts parse of timestamps/inputs | mitigate | Date.parse with NaN -> null/excluded; never eval; rendered via React text nodes (auto-escaped) |
| T-cqn-02 | Denial of Service | 1000-entry retained payload | mitigate | Payload size measured in Task 3 (~150 KB); broker/client limits verified; list rendering is a single filter pass |
| T-cqn-03 | Information Disclosure | larger retained history | accept | Same read-only broker credentials and LAN scope as before; only device ids and state transitions, already exposed |
</threat_model>

<verification>
- dashboard-react: `npm run typecheck`, `npm test`, `npm run build` all pass.
- repo root: `uv run pytest tests/test_mqtt_poller.py -q` passes; `uvx ruff check --no-cache` shows 7 pre-existing findings, no new ones.
- EventHistory.tsx still has exactly one `slice().reverse()` and its load-bearing comment.
</verification>

<success_criteria>
- Event rows show local YYYY-MM-DD HH:MM:SS.
- From/To filter with Clear, distinct "No events in this range" state, accessible labels, reversed-range error.
- Cap is 1000 in poller default, compose, and tests; payload/limits verification recorded as VERIFIED vs ASSUMED.
- Podman doc row and dashboard README updated.
</success_criteria>

<output>
Create `.planning/quick/260925-cqn-event-history-date-time-display-and-date/260925-cqn-SUMMARY.md` when done.
</output>
