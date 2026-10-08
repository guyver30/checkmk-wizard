---
phase: quick-261008-kr3
plan: 01
subsystem: dashboard-react
tags: [dashboard, charts, cpu, history, clickhouse]
key-files:
  created:
    - dashboard-react/src/lib/historyCharts.ts
    - dashboard-react/src/lib/chartCommon.ts
    - dashboard-react/src/hooks/useChartZoom.ts
    - dashboard-react/src/components/ChartZoomToolbar.tsx
    - dashboard-react/src/components/ChartDialogFrame.tsx
    - dashboard-react/src/components/HistoryChart.tsx
    - dashboard-react/src/components/MetricHistoryDialog.tsx
  modified:
    - dashboard-react/src/lib/historyClient.ts
    - dashboard-react/src/components/ForecastChart.tsx
    - dashboard-react/src/components/ForecastDialog.tsx
    - dashboard-react/src/components/HostDetails.tsx
    - dashboard-react/README.md
    - .planning/phases/14.2-fleet-failure-prediction-and-incident-narration/14.2-UI-SPEC.md
completed: 2026-10-08
---

# Quick 261008-kr3: CPU history charts Summary

CPU utilization is now a history-only chart (measured line plus Checkmk warn/crit lines), and the Load gauge opens a new three-line (1/5/15 min) load history chart with absolute warn/crit lines; both share the forecast chart's zoom and pan through an extracted hook and toolbar.

## Commits

- bba0808 history series fetch and shared chart helpers (Task 1)
- f7cf50e shared zoom hook, toolbar, ForecastChart switched over, HistoryChart (Task 2)
- b08a49f ChartDialogFrame, MetricHistoryDialog, util dispatch in ForecastDialog (Task 3)
- b8fa6a5 gauge History buttons, Trends filter, README and UI-SPEC (Task 4)

## Design

Sibling HistoryChart built on extracted pieces (useChartZoom, ChartZoomToolbar, chartCommon), not a mode prop on ForecastChart. ForecastDialog became a hook-free dispatcher: history-only metrics (util, load1, load5, load15) go to HistoryOnlyMetricDialog, everything else to the unchanged forecast view (ForecastView), so every existing util entry point (need rows, Trends, NeedsPane) lands on the history view.

No poller, analytics, ClickHouse or nginx change was needed: load1/load5/load15 are already in history.metrics and readable by dashboard_reader. Analytics still publishes the util fit; the dashboard ignores it (the dialog uses only its warn/crit as a fallback level and its unit, and the Trends list skips it).

## Verification actually run (in dashboard-react)

- `npx vitest run` (full suite): 65 files, 910 tests passed.
- `npx tsc --noEmit`: clean (no output). `npx tsc -b --noEmit`: clean.
- `npm run lint` (oxlint): warnings only, no errors. The remaining warnings are in files this plan did not introduce (StateBadge, ThreePaneLayout, GroupingControls, TopologyMap, AlertsPane, StatsStrip, and ForecastDialog's two pre-existing react warnings: only-export-components for defaultRange and set-state-in-effect). Two new immutability warnings in HostDetails (openChart/openLoadChart read before declaration) were fixed by moving the handlers above `gauges`; a grep of lint output for every file touched shows no warnings attributable to this change.
- ForecastChart.test.tsx (22 cases, the plan said 23), ForecastDialog.test.tsx and chartZoom.test.ts pass with zero edits (`git diff` on those files is empty). `git diff 2af0997 HEAD` shows no change to scripts/, analytics/, deploy/, chartZoom.ts.
- HistoryChart.tsx contains no FitPayload, slope, warn_ts or crit_ts reference (grep count 0).

## NOT verified

The change was not seen in a browser. Only jsdom component tests ran. Real wheel/drag behaviour, layout, colors and the live ClickHouse data were not checked.

## Deviations from Plan

**1. [Rule 1 - necessary test change] HostDetails.test.tsx existing assertion**
- The agent-host test asserted `queryByText("History")` is absent (meaning the removed event-history section). The plan requires visible "History" button text on the gauges, so the assertion now checks `queryByRole("heading", { name: "History" })` instead, with a comment. Intent (no history section) is preserved.
- The "lists every fit under Trends" case was changed as the plan directed: the util entry is now asserted absent (comment names the operator decision).
- Neither ForecastChart.test.tsx nor ForecastDialog.test.tsx needed edits.

**2. [Rule 3] worktree base** The worktree started at b1be292; reset to 2af0997 as instructed by the dispatch.

**3.** The `reveal` of the hook uses the existing `revealTime`, so crosshair stepping keeps ForecastChart's behaviour exactly.

## Known Stubs

None.

## Operator checklist (manual, in a browser)

1. Open host details for an agent host, click History under CPU: measured line plus Warn/Crit lines, no dashed projection, no confidence/Stable/No clear trend text, no date markers, no Today line.
2. Click History under Load: three lines (1 min, 5 min, 15 min) with legend and Warn/Crit at the absolute levels shown on the gauge.
3. Wheel, drag, +/-/0, Shift+Arrow and double-click on both charts.
4. Pick a host or range with no rows and see "No history in this range."
5. Confirm the rows exist in ClickHouse, via clickhouse-client in the clickhouse container:

```sql
SELECT host, metric, count() AS n, min(ts), max(ts) FROM history.metrics WHERE service = 'CPU load' AND metric IN ('load1','load5','load15') AND ts >= now() - INTERVAL 1 DAY GROUP BY host, metric ORDER BY host, metric;
```

or via the dashboard:

```
curl -sG 'http://<dashboard-host>/ch-api/' --data-urlencode "query=SELECT host, metric, count() AS n FROM history.metrics WHERE service = 'CPU load' AND metric IN ('load1','load5','load15') AND ts >= now() - INTERVAL 1 DAY GROUP BY host, metric ORDER BY host, metric FORMAT PrettyCompact"
```

Expect three rows per agent host; zero rows means the poller is not seeing the "CPU load" service perf data and the chart will show the empty message.

Deploy needs `podman compose build dashboard`, then a full `podman compose down && podman compose up -d` (restarting a single container breaks Checkmk egress).

## Self-Check: PASSED

All created files exist and the four commits are in `git log`.
