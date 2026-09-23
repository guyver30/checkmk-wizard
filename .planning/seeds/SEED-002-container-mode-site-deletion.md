---
id: SEED-002
status: dormant
planted: 2026-09-23
planted_during: v1.0 (Phase 12 complete, Phase 13 next)
trigger_when: an operator hits this limitation in container mode and asks for a way to delete/reset a site without dropping into a shell on the Checkmk host themselves
scope: small (option 1, a message-only change) to medium (option 2, a deliberate container-boundary exception)
---

# SEED-002: Container-mode site deletion is unsupported by design — decide between "tell the operator to run omd rm" and "let the wizard cross the container boundary"

## Why This Matters

In host-native mode, `phase1_site_bringup()` (`src/checkmk_wizard/wizard.py`, ~lines 372-461) offers a
"Delete a site, then create a new one" menu choice, backed by `site.list_sites()`/`site.remove_site()`
in `src/checkmk_wizard/site.py`, both of which shell out to the local `omd` CLI.

In container mode (`container_mode = not site.omd_installed()`, same function, ~lines 385-399), the
wizard skips straight to connecting to an existing site and never enters the `existing_sites` loop that
offers deletion at all — there is no local `omd` to call from the worker container. This is correct,
deliberate behavior, not a bug: deleting/decommissioning an OMD site (stopping its processes, removing
its system user/group/home directory/config/data) is an OS-level operation only `omd rm`, run locally on
the machine hosting the site, can perform.

**Ruled out during investigation (2026-09-23, verified via context7 against Checkmk's docs/source):**
Checkmk's REST API has a `site_connection` domain type (`DELETE /objects/site_connection/{site_id}`),
but that only removes a *distributed-monitoring* connection from a central site to a remote site — it
does not decommission the remote site's actual installation, and it doesn't apply at all to this
project's single-site (non-distributed) setup. There is no REST API equivalent of `omd rm`.

So closing this gap is a genuine two-way fork, not a bug fix:

1. **Tell the operator to run `omd rm <site>` themselves** on the Checkmk host/container when they want
   to delete a site while running the wizard in container mode. No code change beyond a clearer message
   than what's printed today (the current container-mode message already explains creation/deletion
   aren't available from here, but doesn't tell the operator what to run instead).
2. **Let the wizard cross the container boundary itself** (e.g. exec into the Checkmk container, or some
   other mechanism) to run `omd rm` on the operator's behalf. This would be a deliberate, documented
   exception to the project's core container-boundary constraint — the worker touches Checkmk only via
   the REST API and Livestatus-over-TCP, never its filesystem (see root `CLAUDE.md` Constraints and
   `site.py`'s own design commentary) — so it needs explicit buy-in when it's picked up, not a quiet
   workaround slipped into an unrelated phase.

## When to Surface

**Trigger:** an operator actually hits this limitation in container mode and asks for a way to
delete/reset a site without dropping into a shell on the Checkmk host themselves.

This seed will surface during `/bm:new-milestone` when the milestone scope matches, or can be pulled
forward manually whenever the trigger condition arrives.

## Scope Estimate

- **Option 1** (message-only): small — a few hours. Print `omd rm <site>` (and maybe the exact command)
  in the container-mode message at `wizard.py:385-399` instead of just saying deletion isn't available.
- **Option 2** (cross the boundary): medium — needs its own discuss-phase, since it's a constraint
  exception, not a routine feature. Needs a decision on *how* the wizard would reach the Checkmk
  container's `omd` (exec, SSH, a privileged sidecar, etc.) and what guardrails apply.

## Breadcrumbs

- `src/checkmk_wizard/wizard.py:372-461` — `phase1_site_bringup()`, container-mode branch (~385-399) and
  the host-native delete flow (~401-461) it skips
- `src/checkmk_wizard/site.py` — `list_sites()`, `remove_site()`, `omd_installed()`
- Root `CLAUDE.md` → Constraints → "Container boundary" (the constraint an eventual Option 2 would need
  to deliberately except itself from)

## Notes

Captured from a conversation on 2026-09-23 confirming this is by-design (not a gap) and ruling out a
Checkmk REST API path via `site_connection` (that endpoint solves distributed-monitoring topology, not
site lifecycle). The user's own framing: they'd either tell the operator to run the `omd` CLI themselves,
or eventually cross the container boundary and let the wizard do it — both captured above as the two
resolution options.
