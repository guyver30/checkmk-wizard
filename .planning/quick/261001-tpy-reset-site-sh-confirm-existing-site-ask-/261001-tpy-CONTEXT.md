# Quick Task 261001-tpy: reset-site.sh — confirm existing site, ask new name, Esc aborts - Context

**Gathered:** 2026-10-01
**Status:** Ready for planning

<domain>
## Task Boundary
Make `deploy/reset-site.sh` the one place to start over AND rename the Checkmk site
(container mode), removing the chicken/egg confusion between `CMK_SITE_ID` in
`deploy/.env` and the site that actually exists in the `checkmk_data` volume.
`compose.yaml` only carries the `${CMK_SITE_ID:-dmc}` fallback and is NOT edited.
</domain>

<decisions>
## Implementation Decisions

### Existing site detection + confirmation
- Detect the site(s) actually present in the `${project}_checkmk_data` volume, not just
  `.env`: prefer `podman exec checkmk ls /omd/sites` when the checkmk container is running;
  otherwise run a throwaway container from the already-present checkmk image with the volume
  mounted read-only (no new image pull). If the volume does not exist, say so (nothing to delete).
- Show the existing site name and the value in `.env` (and warn if they differ).
- Confirmation: operator types the EXISTING site name (as today, but the real one, not the .env value).
  `--yes` still skips the prompt and keeps the current name.

### New site name
- After confirmation, prompt "New site name [<existing>]:" — default = existing name.
- Validate with the same rule as init-env.sh / the wizard (`^[A-Za-z][A-Za-z0-9_]{0,15}$`), re-ask on invalid.
- Write it to `deploy/.env` (`CMK_SITE_ID=`), reusing init-env.sh's set_val approach (replace
  existing line, or uncomment `# CMK_SITE_ID=`, or append). Must happen BEFORE `podman compose up -d`
  so the entrypoint creates the site under the new name. Update every later message (wait-loop URL,
  LIVESTATUS_TCP_TLS check, "Next:" hints) to use the new name.
- Add an optional `--site NAME` flag for non-interactive use together with `--yes`.

### Esc aborts
- Pressing Esc at any prompt (confirmation or new-name) aborts with "Aborted." and exit 1, before
  anything was changed (no `compose down`, no volume removal, no .env write).
- Ctrl+C must also abort cleanly before changes. Implementation is Claude's discretion (e.g. a
  small read-line helper using `read -rsn1` that detects $'\e', handles Backspace and Enter, and
  echoes typed chars).

### Order of operations (must be preserved)
1. Pre-flight: `.env` must make compose parse — if `podman compose config -q` fails, tell the
   operator to run `deploy/init-env.sh` first and exit before any prompt.
2. Detect + confirm + ask new name (Esc-abortable; no changes yet).
3. `podman compose down` → remove volumes → write new CMK_SITE_ID → `podman compose up -d` → wait.

### Claude's Discretion
- Exact helper structure, messages wording.
</decisions>

<specifics>
- Keep the script's existing style (set -euo pipefail, comments explaining why, --help via sed of header).
- Update the header comment/usage and docs that describe reset-site.sh (docs/WIZARD-OPERATION.md
  "Starting over with a blank site", and the Podman setup doc if it mentions renaming) per user CLAUDE.md.
- Verify with `bash -n` and, if available, `uvx shellcheck-py`/shellcheck; test the read helper
  logic by piping input where feasible.
</specifics>
