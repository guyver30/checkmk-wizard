# Quick Task 261001-ts1: wizard Esc abort — summarize pending changes, apply or revert - Context

**Gathered:** 2026-10-01
**Status:** Ready for planning

<domain>
## Task Boundary
Let the operator leave `checkmk-wizard` at any prompt by pressing Esc (Ctrl+C behaves the same).
On abort, the wizard shows the site's pending (not yet activated) changes and asks whether to
APPLY (activate) or REVERT (discard) them, then exits. No more half-finished runs that leave
pending changes for the next run to force-activate silently.
</domain>

<decisions>
## Implementation Decisions

### Where Esc works
- Esc/Ctrl+C at any questionary prompt during Phase 1 through Phase 4 raises one exception
  (e.g. `WizardAborted`) that `run()`/`main()` catch. Today Ctrl+C makes `ask_async()` return
  None, which most call sites don't handle — the abort must not depend on each call site checking None.
- Esc DISABLED from the start of Phase 5 onward (user decision): Phase 5 changes remote machines
  over SSH, which no Checkmk revert can undo. From Phase 5 prompts ignore Esc (Ctrl+C: keep
  today's behaviour or treat as abort-without-prompt — Claude's discretion, but never leave the
  terminal broken). Print a one-line note at Phase 5 start: "Esc is disabled from here on".
- Esc only acts at prompts; during scanning/activation waits nothing reads the keyboard — fine.
- Known prompt_toolkit behaviour: Esc has a short delay (escape-sequence timeout). Acceptable.
  Implementation hint: questionary questions expose the prompt_toolkit Application; add a key
  binding for Escape (eager=True) that exits with an abort, ideally in ONE place (a small wrapper
  used by every prompt, or patching the questionary prompt creation) rather than editing ~48 call
  sites one by one. Verify the mechanism via context7 (questionary / prompt_toolkit docs).

### On abort (Phases 1-4)
- GET pending changes (`CheckmkClient.get_pending_changes()` already exists, REST
  `/domain-types/activation_run/collections/pending_changes`). If the REST client is not yet
  usable (abort during Phase 1 before connection) or there are no pending changes: print
  "Aborted — no pending changes" and exit.
- Otherwise print a table: time, user, action_name, text (html-unescape the text; Checkmk returns
  `&#x27;` etc.). Mark changes by other users ("foreign") clearly.
- Ask: Apply (activate, via existing `_activate_pending_changes`) / Revert (discard ALL pending
  changes) / Leave pending (exit, changes stay for later — print the manual GUI path).
  Default: Revert? -> Claude's discretion, but the prompt must say that Revert discards ALL pending
  changes on the site including other users' ones (Checkmk has no per-change revert).
  Esc in this final prompt = Leave pending.

### Revert mechanism — GUI revert action (user decision)
- Checkmk 2.4.0 REST API has NO revert/discard endpoint (verified 2026-10-01 against
  Checkmk/checkmk source, cmk/gui/openapi/endpoints/activate_changes/__init__.py on branches
  2.4.0, 2.5.0 and master: only activate-changes, wait-for-completion, show, running,
  pending_changes).
- The GUI "Revert changes" button is `ModeRevertChanges` in cmk/gui/wato/pages/activate_changes.py
  (2.4.0): mode name `revert_changes`, action triggered by request var `_action=discard` plus a valid
  `_transid` (transactions.check_transaction). It restores the last automatic WATO snapshot taken at
  the last activation, then activates — reverting ALL pending changes. Requires permissions
  `wato.activate` + `wato.discard` (+ `wato.discardforeign` if foreign changes exist; cmkadmin has
  all). Blocked when no snapshot exists yet or a pending change has `prevent_discard_changes`.
- Implement in `api.py` as a best-effort helper modelled on the existing GUI-session helpers
  (`_gui_login`, `bootstrap_automation_user`): log in as cmkadmin, GET
  `wato.py?mode=revert_changes` to obtain the transid (parse it from the confirm URL / page HTML),
  then request the discard action, then re-GET pending changes to confirm the list is empty.
  Return a success/failure result; never raise to the caller (same contract as other bootstrap
  helpers). Docstring must cite the source file/branch above and state "not yet live-verified on
  2.4.0p35" until verified.
- cmkadmin password: reuse it if Phase 1 collected it this run; otherwise prompt for it at revert time.
- On failure (blocked/no snapshot/login failure): print the reason and the manual path
  "Setup > Activate changes > Revert changes".

### Claude's Discretion
- Exception/wrapper design, table layout, default choice of the final prompt.
</decisions>

<specifics>
- Tests (respx + monkeypatch, no live I/O): abort exception raised by Esc binding; abort in phase 2
  shows pending changes and calls activate / revert helper per choice; no pending -> no prompt;
  Phase 5+ ignores Esc; revert helper: transid parsing, success, blocked/failure paths.
- Docs: docs/WIZARD-OPERATION.md + README (Esc behaviour, phases, revert semantics).
- Note: another quick task (261001-tpy) is concurrently editing deploy/reset-site.sh and docs
  sections about reset-site.sh — avoid touching those sections.
</specifics>

<canonical_refs>
- https://github.com/Checkmk/checkmk/blob/2.4.0/cmk/gui/wato/pages/activate_changes.py (ModeRevertChanges)
- https://github.com/Checkmk/checkmk/blob/2.4.0/cmk/gui/openapi/endpoints/activate_changes/__init__.py
- https://docs.checkmk.com/latest/en/wato.html "Revert changes"
</canonical_refs>
