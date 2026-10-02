// Admin chrome (?admin=1): the persistent ADMIN MODE banner and the bottom action bar with
// its confirm dialog, ack wait and result Snackbar. Rendered only when isAdminMode(); copy
// strings are taken verbatim from the admin UI contract's copywriting table.
//
// The dashboard says "Sent" rather than claiming success: the poller's ack means the command was
// applied to its fake-state map, and the next published status is what proves the change.
// The design system has no Dialog component, so the confirm dialog is a fixed scrim plus a
// role="dialog" panel styled with the same tokens.

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Banner, Button, ButtonGroup, Snackbar, Tooltip } from "kone-design-system";
import { previewCascade, type AdminAction } from "../lib/adminMode";
import { displayName } from "../lib/display";
import type { DevicePayload } from "../lib/types";
import { publishAdminCommand } from "../store/mqttClient";
import { useAdminStore, type AdminResult } from "../store/adminStore";

const ACK_TIMEOUT_MS = 15000;
const CONFIG_ERROR_TEXT =
  "Admin login unavailable. Reload the page, or check that the dashboard container has the admin password configured.";
const NO_ANSWER_TEXT = "No answer from the poller. Check that it is running, then try again.";

const STATE_WORD: Record<AdminAction, string> = {
  up: "UP",
  down: "DOWN",
  unreach: "UNREACHABLE",
  restore: "",
  restore_all: "",
};

function hostsWord(n: number): string {
  return `${n} ${n === 1 ? "host" : "hosts"}`;
}

export function AdminBanner() {
  const faked = useAdminStore((s) => s.faked);
  const configError = useAdminStore((s) => s.configError);
  const n = Object.keys(faked).length;
  const message = configError
    ? CONFIG_ERROR_TEXT
    : `ADMIN MODE - ${n === 0 ? "no hosts" : hostsWord(n)} faked`;
  return (
    <div role="status" className="sticky top-0 z-40">
      <Banner status={configError ? "danger" : "warning"} message={message} />
    </div>
  );
}

interface DialogState {
  action: AdminAction;
  hosts: string[];
}

interface Feedback {
  status: "success" | "danger";
  message: string;
  autoHide: boolean;
}

function dialogTitle(action: AdminAction): string {
  switch (action) {
    case "up":
      return "Set hosts UP";
    case "down":
      return "Set hosts DOWN";
    case "unreach":
      return "Set hosts UNREACHABLE";
    case "restore":
      return "Restore hosts";
    case "restore_all":
      return "Restore all faked hosts";
  }
}

function effectSentence(action: AdminAction, n: number): string {
  switch (action) {
    case "up":
      return `Mark ${hostsWord(n)} UP.`;
    case "down":
      return `Mark ${hostsWord(n)} DOWN. Managed hosts below them become UNREACHABLE.`;
    case "unreach":
      return `Mark ${hostsWord(n)} UNREACHABLE.`;
    case "restore":
      return `Re-enable normal checks on ${hostsWord(n)}.`;
    case "restore_all":
      return `Re-enable normal checks on all ${n} faked hosts.`;
  }
}

function confirmLabel(action: AdminAction, n: number): string {
  switch (action) {
    case "up":
      return `Set ${n} hosts UP`;
    case "down":
      return `Set ${n} hosts DOWN`;
    case "unreach":
      return `Set ${n} hosts UNREACHABLE`;
    case "restore":
      return `Restore ${n} hosts`;
    case "restore_all":
      return `Restore all ${n} faked hosts`;
  }
}

function feedbackFor(result: AdminResult): Feedback {
  if (result.timedOut) {
    return { status: "danger", message: NO_ANSWER_TEXT, autoHide: false };
  }
  if (!result.ok) {
    return {
      status: "danger",
      message: `Could not apply: ${result.detail}. Nothing changed. Try again in a few seconds.`,
      autoHide: false,
    };
  }
  const word = STATE_WORD[result.action as AdminAction];
  const text =
    word === undefined || word === ""
      ? `Sent: ${hostsWord(result.count)} restored`
      : `Sent: ${hostsWord(result.count)} set ${word}`;
  return { status: "success", message: text, autoHide: true };
}

function formatTime(ms: number): string {
  const d = new Date(ms);
  const pad = (v: number) => String(v).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export interface AdminActionBarProps {
  devices: Record<string, DevicePayload>;
  topologyDevices: unknown[];
}

export function AdminActionBar({ devices, topologyDevices }: AdminActionBarProps) {
  const selected = useAdminStore((s) => s.selected);
  const faked = useAdminStore((s) => s.faked);
  const configError = useAdminStore((s) => s.configError);
  const lastResult = useAdminStore((s) => s.lastResult);
  const clearSelection = useAdminStore((s) => s.clearSelection);

  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [waiting, setWaiting] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handledResult = useRef<AdminResult | null>(lastResult);
  const panelRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  const selectedIds = useMemo(() => [...selected].sort(), [selected]);
  const fakedCount = Object.keys(faked).length;
  const noneSelected = selectedIds.length === 0;
  const actionsDisabled = configError || waiting;

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => clearTimer, [clearTimer]);

  // A new store result closes the wait state and becomes the Snackbar.
  useEffect(() => {
    if (!lastResult || lastResult === handledResult.current) {
      return;
    }
    handledResult.current = lastResult;
    clearTimer();
    setWaiting(false);
    setDialog(null);
    setFeedback(feedbackFor(lastResult));
  }, [lastResult, clearTimer]);

  useEffect(() => {
    if (!feedback?.autoHide) {
      return;
    }
    const id = setTimeout(() => setFeedback(null), 6000);
    return () => clearTimeout(id);
  }, [feedback]);

  const cancel = useCallback(() => {
    if (!waiting) {
      setDialog(null);
    }
  }, [waiting]);

  // Escape clears the selection when no dialog is open; with a dialog open it cancels.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      if (dialog) {
        cancel();
      } else {
        clearSelection();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [dialog, cancel, clearSelection]);

  useEffect(() => {
    if (dialog) {
      cancelRef.current?.focus();
    }
  }, [dialog]);

  const open = (action: AdminAction, hosts: string[]) => {
    setFeedback(null);
    setDialog({ action, hosts });
  };

  const confirm = () => {
    if (!dialog || waiting) {
      return;
    }
    const id = publishAdminCommand(dialog.action, dialog.hosts);
    if (id === null) {
      setDialog(null);
      setFeedback({
        status: "danger",
        message:
          "Could not apply: not connected to the broker. Nothing changed. Try again in a few seconds.",
        autoHide: false,
      });
      return;
    }
    setWaiting(true);
    clearTimer();
    timerRef.current = setTimeout(() => {
      useAdminStore.getState().expirePending(id);
    }, ACK_TIMEOUT_MS);
  };

  const trapTab = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || !panelRef.current) {
      return;
    }
    const focusable = panelRef.current.querySelectorAll<HTMLElement>("button:not([disabled])");
    if (focusable.length === 0) {
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const nameFor = (id: string) => displayName(devices[id] ?? { id });
  const cascaded = useMemo(
    () => (dialog?.action === "down" ? previewCascade(dialog.hosts, topologyDevices) : []),
    [dialog, topologyDevices],
  );

  const restoreAllButton = (
    <Button
      variant="secondary"
      disabled={actionsDisabled || fakedCount === 0}
      onClick={() => open("restore_all", [])}
    >
      Restore all
    </Button>
  );

  const destructive = dialog?.action === "down" || dialog?.action === "unreach" || dialog?.action === "restore_all";

  return (
    <>
      <div className="flex items-center gap-2 border-t bg-bg-subtle p-4" data-testid="admin-action-bar">
        <div className="flex flex-col">
          <span className="text-sm font-semibold text-fg-primary">
            {noneSelected ? "No hosts selected" : `${selectedIds.length} selected`}
          </span>
          {noneSelected && (
            <span className="text-xs text-fg-tertiary">
              Ctrl+click hosts on the map or in the tree, or tick a folder, then choose an action.
            </span>
          )}
        </div>
        <Button variant="tertiary" disabled={noneSelected} onClick={clearSelection}>
          Clear selection
        </Button>
        <ButtonGroup>
          <Button variant="secondary" disabled={noneSelected || actionsDisabled} onClick={() => open("up", selectedIds)}>
            Set UP
          </Button>
          <Button variant="secondary" disabled={noneSelected || actionsDisabled} onClick={() => open("down", selectedIds)}>
            Set DOWN
          </Button>
          <Button variant="secondary" disabled={noneSelected || actionsDisabled} onClick={() => open("unreach", selectedIds)}>
            Set UNREACHABLE
          </Button>
          <Button variant="secondary" disabled={noneSelected || actionsDisabled} onClick={() => open("restore", selectedIds)}>
            Restore selected
          </Button>
        </ButtonGroup>
        <div className="ml-auto flex items-center gap-3">
          {lastResult && !lastResult.timedOut && (
            <span className="text-xs text-fg-tertiary">
              {`Last: ${lastResult.action} ${hostsWord(lastResult.count)}, ${formatTime(lastResult.atMs)}`}
            </span>
          )}
          {fakedCount === 0 ? (
            <Tooltip content="No hosts are faked" position="top">
              {restoreAllButton}
            </Tooltip>
          ) : (
            restoreAllButton
          )}
        </div>
      </div>

      {dialog && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={cancel}
          data-testid="admin-scrim"
        >
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-dialog-title"
            className="w-full max-w-md rounded-md bg-bg-primary p-6 shadow-lg"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={trapTab}
          >
            <h2 id="admin-dialog-title" className="text-xl font-semibold text-fg-primary">
              {dialogTitle(dialog.action)}
            </h2>
            <p className="mt-2 text-sm text-fg-secondary">
              {effectSentence(dialog.action, dialog.action === "restore_all" ? fakedCount : dialog.hosts.length)}
            </p>
            {dialog.action !== "restore_all" && (
              <div className="mt-4 max-h-60 overflow-auto rounded-md bg-bg-subtle p-3">
                {dialog.action === "down" ? (
                  <>
                    <p className="text-xs font-semibold text-fg-secondary">{`Selected (${dialog.hosts.length})`}</p>
                    <ul className="mb-2 text-sm text-fg-primary">
                      {dialog.hosts.map((id) => (
                        <li key={id}>{nameFor(id)}</li>
                      ))}
                    </ul>
                    {cascaded.length > 0 && (
                      <>
                        <p className="text-xs font-semibold text-fg-secondary">{`Also set UNREACHABLE (${cascaded.length})`}</p>
                        <ul className="text-sm text-fg-primary">
                          {cascaded.map((id) => (
                            <li key={id}>{nameFor(id)}</li>
                          ))}
                        </ul>
                      </>
                    )}
                  </>
                ) : (
                  <>
                    <p className="text-xs font-semibold text-fg-secondary">{`${dialog.hosts.length} hosts`}</p>
                    <ul className="text-sm text-fg-primary">
                      {dialog.hosts.map((id) => (
                        <li key={id}>{nameFor(id)}</li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <Button ref={cancelRef} variant="secondary" disabled={waiting} onClick={cancel}>
                Cancel
              </Button>
              <Button
                variant={destructive ? "destructive" : "primary"}
                loading={waiting}
                onClick={confirm}
              >
                {confirmLabel(dialog.action, dialog.action === "restore_all" ? fakedCount : dialog.hosts.length)}
              </Button>
            </div>
          </div>
        </div>
      )}

      {feedback && (
        <div
          className="fixed bottom-16 left-4 z-50"
          aria-live={feedback.status === "danger" ? "assertive" : "polite"}
        >
          <Snackbar
            status={feedback.status}
            message={feedback.message}
            actionLabel="Dismiss"
            onAction={() => setFeedback(null)}
          />
        </div>
      )}
    </>
  );
}
