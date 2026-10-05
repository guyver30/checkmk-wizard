// Triage (available in every dashboard mode) for one Service need (D-21, D-22, D-24): a "Triage" menu with Downgrade,
// Upgrade to immediate and Cancel need. Cancel asks for confirmation with an optional reason.
//
// No ack topic exists: the visible effect of a command is the republished need. The UI
// therefore says "Sent", never "confirmed", and checks the store 15 s later; if the need did
// not change it shows a persistent error. The design system has no Dialog component, so the
// confirm dialog is a fixed scrim plus a role="dialog" panel (same approach as AdminBar.tsx).

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Button, Input, Snackbar, Tooltip } from "kone-design-system";
import { buildTriageCommand, type TriageAction, type TriageCommand } from "../lib/triageMode";
import type { NeedPayload } from "../lib/types";
import { publishTriage } from "../store/triageClient";
import { useAppStore } from "../store/useAppStore";

export const TRIAGE_CHECK_MS = 15000;
const LOGIN_UNAVAILABLE_TEXT =
  "Triage login unavailable. Reload the page, or check the dashboard container configuration.";
const NO_UPDATE_TEXT =
  "Could not apply: no update received from the analytics service. Nothing changed. Try again in a few seconds.";

export interface TriageMenuProps {
  need: NeedPayload;
  hostLabel: string;
  // Injectable for tests.
  publish?: (cmd: TriageCommand) => Promise<boolean>;
}

interface Feedback {
  status: "success" | "danger";
  message: string;
  autoHide: boolean;
}

const ACTION_WORD: Record<TriageAction, string> = {
  downgrade: "downgrade",
  upgrade: "upgrade to immediate",
  cancel: "cancel need",
};

function whatText(need: NeedPayload): string {
  if (need.service === "") {
    return "Host";
  }
  return need.metric ? `${need.service} · ${need.metric}` : need.service;
}

function MenuItem({
  label,
  onSelect,
  disabledReason,
}: {
  label: string;
  onSelect: () => void;
  disabledReason?: string;
}) {
  const button = (
    <button
      role="menuitem"
      disabled={disabledReason !== undefined}
      onClick={onSelect}
      className="flex w-full items-center px-3 py-2 text-left text-sm text-fg-primary hover:bg-bg-surface-hover disabled:cursor-not-allowed disabled:text-fg-disabled"
    >
      {label}
    </button>
  );
  return disabledReason ? (
    <Tooltip content={disabledReason} position="left">
      {button}
    </Tooltip>
  ) : (
    button
  );
}

export function TriageMenu({ need, hostLabel, publish = publishTriage }: TriageMenuProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [loginUnavailable, setLoginUnavailable] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const needId = need.id;
  const what = whatText(need);

  useEffect(
    () => () => {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (confirming) {
      keepRef.current?.focus();
    }
  }, [confirming]);

  useEffect(() => {
    if (!feedback?.autoHide) {
      return;
    }
    const id = setTimeout(() => setFeedback(null), 6000);
    return () => clearTimeout(id);
  }, [feedback]);

  const send = async (action: TriageAction, note?: string) => {
    setMenuOpen(false);
    setFeedback(null);
    const baseline = need.triage?.set_at ?? null;
    const ok = await publish(buildTriageCommand(needId, action, note));
    if (!ok) {
      setLoginUnavailable(true);
      setFeedback({ status: "danger", message: LOGIN_UNAVAILABLE_TEXT, autoHide: false });
      return;
    }
    setFeedback({
      status: "success",
      message: `Sent: ${ACTION_WORD[action]} for ${hostLabel}, ${what}`,
      autoHide: true,
    });
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
    }
    timerRef.current = setTimeout(() => {
      const current = useAppStore.getState().needs[needId];
      const changed =
        action === "cancel"
          ? current === undefined || current.triage?.action === "cancel"
          : current !== undefined && (current.triage?.set_at ?? null) !== baseline;
      if (!changed) {
        setFeedback({ status: "danger", message: NO_UPDATE_TEXT, autoHide: false });
      }
    }, TRIAGE_CHECK_MS);
  };

  const closeDialog = () => {
    setConfirming(false);
    setReason("");
  };

  const confirmCancel = () => {
    const note = reason;
    closeDialog();
    void send("cancel", note);
  };

  const trapTab = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      closeDialog();
      return;
    }
    if (event.key !== "Tab" || !panelRef.current) {
      return;
    }
    const focusable = panelRef.current.querySelectorAll<HTMLElement>("button:not([disabled]), input");
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

  const onMenuKey = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      setMenuOpen(false);
    }
  };

  const standard = need.tier === "standard";
  const immediate = need.tier === "immediate";

  const trigger = (
    <Button
      variant="tertiary"
      size="sm"
      disabled={loginUnavailable}
      aria-haspopup="menu"
      aria-expanded={menuOpen}
      onClick={() => setMenuOpen((open) => !open)}
    >
      Triage
    </Button>
  );

  return (
    <div className="relative" onKeyDown={onMenuKey}>
      {loginUnavailable ? (
        <Tooltip content={LOGIN_UNAVAILABLE_TEXT} position="top">
          {trigger}
        </Tooltip>
      ) : (
        trigger
      )}
      {menuOpen && (
        <div
          role="menu"
          aria-label="Triage"
          className="absolute right-0 z-30 mt-1 w-52 rounded-md border border-neutral-150 bg-bg-surface py-1.5 shadow-menu"
        >
          <MenuItem
            label="Downgrade"
            onSelect={() => void send("downgrade")}
            disabledReason={standard ? "Already standard" : undefined}
          />
          <MenuItem
            label="Upgrade to immediate"
            onSelect={() => void send("upgrade")}
            disabledReason={immediate ? "Already immediate" : undefined}
          />
          <MenuItem
            label="Cancel need"
            onSelect={() => {
              setMenuOpen(false);
              setConfirming(true);
            }}
          />
        </div>
      )}

      {confirming && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={closeDialog}
          data-testid="triage-scrim"
        >
          <div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={`triage-title-${needId}`}
            className="w-full max-w-md rounded-md bg-bg-primary p-6 shadow-lg"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={trapTab}
          >
            <h2 id={`triage-title-${needId}`} className="text-xl font-semibold text-fg-primary">
              Cancel this need?
            </h2>
            <p className="mt-2 text-sm text-fg-secondary">
              {`${hostLabel}, ${what} will be hidden from the Service needs pane until it resolves and comes back. The action is recorded.`}
            </p>
            <div className="mt-4">
              <Input
                id={`triage-reason-${needId}`}
                label="Reason (optional)"
                value={reason}
                maxLength={200}
                onChange={(event) => setReason(event.target.value)}
              />
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button ref={keepRef} variant="secondary" onClick={closeDialog}>
                Keep need
              </Button>
              <Button variant="destructive" onClick={confirmCancel}>
                Cancel need
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
    </div>
  );
}
