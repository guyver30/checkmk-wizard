// Banner above the topology toolbar listing hosts that someone other than topology_editor (in
// practice Checkmk's network scan) created and left pending, with a one-click Activate.
//
// Why this exists: operator decision 2026-10-12 (quick 261012-fx1) relaxes the T-13-17 rule
// ("topology_editor never activates foreign changes") for this one action. The role now holds
// wato.activateforeign; edit-mode Apply still sends force_foreign_changes false, and only this
// banner's Activate passes true.
//
// The pending_changes entry shape is NOT live-verified. The parsing in lib/checkmkWrite.ts is
// defensive: when pending changes exist but no host name can be extracted, the banner falls
// back to a generic "N pending changes" message with the same Activate / Not now actions.
//
// Checkmk activation is all-or-nothing: activating the discovered hosts also activates any other
// users' non-host changes. When there are such changes the first Activate click only shows how
// many and asks for a second confirmation. The click passes expectedChangeKeys (every pending
// key the operator was shown) so a change that arrived afterwards aborts with a 409 instead of
// going live unseen.
//
// "Not now" hides the banner for the browser session (sessionStorage, guarded: component state
// is the source of truth for the mount, storage only lets the dismissal survive a reload).
// The hosts stay pending in Checkmk.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Banner, Button } from "kone-design-system";
import {
  CheckmkWriteError,
  activateChanges,
  classifyPendingChanges,
  getHostSummary,
  listPendingChanges,
  type PendingChange,
  TOPOLOGY_EDITOR_USER,
} from "../lib/checkmkWrite";

const PENDING_POLL_MS = 60_000;
const DISMISS_KEY = "discoveredHostsBanner.dismissed";
const FAILURE_MESSAGE =
  "Activation failed: finish it in Checkmk (Setup > Activate changes) or press Activate again.";

interface HostDetail {
  ip: string | null;
  folder: string | null;
}

function readDismissed(): Set<string> {
  try {
    const raw = sessionStorage.getItem(DISMISS_KEY);
    if (raw === null) {
      return new Set();
    }
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return new Set();
    }
    return new Set(parsed.filter((k): k is string => typeof k === "string"));
  } catch {
    return new Set();
  }
}

function writeDismissed(keys: string[]): void {
  try {
    sessionStorage.setItem(DISMISS_KEY, JSON.stringify(keys));
  } catch {
    // Storage blocked or full: the in-memory dismissal still holds for this mount.
  }
}

export interface DiscoveredHostsBannerProps {
  enabled: boolean;
  onActivated: (hostCount: number) => void;
  onFailed: (message: string) => void;
}

export function DiscoveredHostsBanner({
  enabled,
  onActivated,
  onFailed,
}: DiscoveredHostsBannerProps) {
  const [changes, setChanges] = useState<PendingChange[]>([]);
  const [details, setDetails] = useState<Record<string, HostDetail>>({});
  const [dismissed, setDismissed] = useState<Set<string>>(() => readDismissed());
  const [confirming, setConfirming] = useState(false);
  const [running, setRunning] = useState(false);
  const [staleNote, setStaleNote] = useState(false);
  const requestedHosts = useRef<Set<string>>(new Set());
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      const next = await listPendingChanges();
      if (aliveRef.current) {
        setChanges(next);
      }
    } catch {
      // Informational surface: a failed read leaves the banner as it was.
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    void load();
    const id = setInterval(() => void load(), PENDING_POLL_MS);
    return () => clearInterval(id);
  }, [enabled, load]);

  const classification = useMemo(() => classifyPendingChanges(changes), [changes]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    for (const { host } of classification.newHosts) {
      if (requestedHosts.current.has(host)) {
        continue;
      }
      requestedHosts.current.add(host);
      getHostSummary(host)
        .then((summary) => ({ ip: summary.ip, folder: summary.folder }))
        .catch(() => ({ ip: null, folder: null }))
        .then((detail) => {
          if (aliveRef.current) {
            setDetails((prev) => ({ ...prev, [host]: detail }));
          }
        });
    }
  }, [enabled, classification.newHosts]);

  const hostCount = classification.newHosts.length;
  // Any foreign change blocks edit-mode Apply (Checkmk refuses to activate with another user's
  // change pending), so a foreign non-host change -- e.g. a host deleted in the Checkmk GUI --
  // also surfaces here, in the generic form, instead of leaving the operator stuck. 2026-10-12.
  const genericCount =
    classification.unnamedHostCreations + classification.unknownShape + classification.otherForeign;
  const genericMode = hostCount === 0 && genericCount > 0;
  const foreignTotal =
    hostCount + classification.unnamedHostCreations + classification.otherForeign +
    classification.unknownShape;
  const allDismissed =
    classification.allKeys.length > 0 &&
    classification.allKeys.every((key) => dismissed.has(key));

  const onNotNow = useCallback(() => {
    const keys = classification.allKeys;
    setDismissed((prev) => new Set([...prev, ...keys]));
    writeDismissed(keys);
    setConfirming(false);
  }, [classification.allKeys]);

  const runActivation = useCallback(async () => {
    if (running) {
      return;
    }
    setRunning(true);
    setStaleNote(false);
    const count = genericMode ? foreignTotal : hostCount;
    try {
      await activateChanges({
        forceForeignChanges: true,
        expectedChangeKeys: classification.allKeys,
      });
      if (aliveRef.current) {
        setChanges([]);
        setConfirming(false);
      }
      onActivated(count);
      void load();
    } catch (err) {
      if (err instanceof CheckmkWriteError && err.status === 409) {
        if (aliveRef.current) {
          setConfirming(false);
          setStaleNote(true);
        }
        void load();
      } else {
        onFailed(FAILURE_MESSAGE);
      }
    } finally {
      if (aliveRef.current) {
        setRunning(false);
      }
    }
  }, [running, genericMode, foreignTotal, hostCount, classification.allKeys, onActivated, onFailed, load]);

  const onActivateClick = useCallback(() => {
    if (!genericMode && classification.otherForeign > 0 && !confirming) {
      setConfirming(true);
      return;
    }
    void runActivation();
  }, [genericMode, classification.otherForeign, confirming, runActivation]);

  if (!enabled || allDismissed || (hostCount === 0 && !genericMode)) {
    return null;
  }

  const heading = genericMode
    ? `${foreignTotal} pending change${foreignTotal === 1 ? "" : "s"} awaiting activation`
    : "New hosts discovered, awaiting activation";

  // What the generic form will activate, so the operator is not asked to approve a bare count.
  const foreignTexts = changes
    .filter((change) => change.user_id !== TOPOLOGY_EDITOR_USER)
    .map((change) => change.text ?? change.action_name ?? "(no description)")
    .slice(0, 5);

  const ownNote = classification.own > 0 ? `, ${classification.own} of your own topology edits` : "";
  const alsoPending =
    !genericMode && classification.otherForeign > 0
      ? `Also pending: ${classification.otherForeign} other change${
          classification.otherForeign === 1 ? "" : "s"
        } by other users${ownNote}`
      : null;

  return (
    <div
      className="flex flex-col gap-2 rounded-md bg-bg-subtle p-3"
      data-testid="discovered-hosts-banner"
    >
      <Banner
        status="info"
        message={
          <>
            <span className="font-semibold">{heading}</span>
            {genericMode && (
              <ul className="mt-1 text-xs">
                {foreignTexts.map((text, index) => (
                  <li key={index}>{text}</li>
                ))}
              </ul>
            )}
            {!genericMode && (
              <ul className="mt-1 text-xs">
                {classification.newHosts.map(({ host }) => {
                  const detail = details[host];
                  return (
                    <li key={host}>
                      {host} - {detail ? (detail.ip ?? "IP unknown") : "…"} -{" "}
                      {detail ? (detail.folder ?? "/") : "…"}
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        }
      />
      {alsoPending && <p className="text-xs text-fg-tertiary">{alsoPending}</p>}
      {staleNote && (
        <p className="text-xs text-fg-tertiary">
          Pending changes changed - review the list and confirm again.
        </p>
      )}
      {confirming && (
        <p className="text-xs text-fg-tertiary">
          Checkmk activates all pending changes at once: {classification.otherForeign} other
          pending change{classification.otherForeign === 1 ? "" : "s"} by other users will also go
          live.
        </p>
      )}
      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          disabled={running}
          loading={running}
          onClick={onActivateClick}
        >
          {confirming ? "Activate all" : "Activate"}
        </Button>
        <Button
          variant="secondary"
          disabled={running}
          onClick={confirming ? () => setConfirming(false) : onNotNow}
        >
          {confirming ? "Cancel" : "Not now"}
        </Button>
      </div>
    </div>
  );
}
