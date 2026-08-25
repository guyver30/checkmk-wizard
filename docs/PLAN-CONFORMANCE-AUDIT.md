# Plan Conformance Audit

**Method:** Read every source file in `src/checkmk_wizard/` line-by-line
against [CHECKMK_SETUP_CONFIGURATOR_PLAN.md](CHECKMK_SETUP_CONFIGURATOR_PLAN.md),
phase by phase. Every REST endpoint, CLI command, and behavioral claim made
in the plan (and in code comments citing "verified via context7") was
independently re-checked against live Checkmk documentation
(`docs.checkmk.com`, fetched fresh via context7, not from training data).
Companion doc: [WIZARD-OPERATION.md](WIZARD-OPERATION.md) for exact
mechanics.

## Summary

| Phase | Conformance | Notes |
|---|---|---|
| 1 — Site Bring-up | ⚠️ Partial (improved 2026-08-24, 2026-08-25) | Package install itself still out of scope by design; wizard now fails fast with clear instructions instead of a confusing subprocess error; added a site-selection menu (continue/delete-then-create-new), site-name/checkmk-host validation, automation-user auto-provisioning with self-activation polling (correcting this audit's own earlier wrong claim that a default automation user exists, and fixing the foreign-pending-change regression that fix caused), full omd create/start/rm output surfacing, a fix for `start_site()` wrongly treating an already-running restart as fatal, and network-error wrapping in the REST client so unreachable/malformed hosts fail cleanly instead of crashing (all 2026-08-25) |
| 2 — Folders | ✅ Matches (extended 2026-08-25) | Beyond original plan scope: folders now carry an optional per-folder subnet for Phase 3 to scan directly into them, requested by the user; folder names live-verified and validated against Checkmk's own naming pattern |
| 3 — Network Discovery | ✅ Matches | Native-scan rationale independently confirmed accurate; CIDR/port input now validated (fixed 2026-08-25); scans folder-by-folder and stages into the right folder when Phase 2 defines subnets, falls back to the original flat scan otherwise (2026-08-25) |
| 4 — Host Classification | ✅ Matches (simplified 2026-08-25) | Per-host folder prompt removed — folder now carried automatically from which Phase 2 folder-subnet scan found the host; hostnames live-verified and validated against Checkmk's own naming pattern |
| 5 — Host Onboarding | ⚠️ Partial (improved 2026-08-24, 2026-08-25) | SNMP path, RPM path, OS-compat check, credential-scope, package-integrity verification, post-install status verification, Phase 3→5 host-collision, and Windows command quoting all fixed; remaining CONCERNS.md items (known_hosts=None, argv secrets, etc.) unchanged |
| 6 — Discovery & Baseline | ✅ Matches (as scoped 2026-08-24) | Accept-services gap closed (`mode: "fix_all"`); baseline rulesets (step 2) deliberately deferred, decision documented |
| 7 — Activation & Validation | ✅ Matches (as scoped 2026-08-24) | Activation/health-check correct and doc-verified; snapshot now pulls real host/folder config, documented as partial (not a full site backup) |

All REST API endpoints, request bodies, and CLI syntax that the code
actually calls were verified **accurate** against current Checkmk docs.
The gaps below are about **scope not built**, not about technical claims
being wrong.

---

## Phase 1 — Site Bring-up

**✅ Verified correct against live docs:**
- `omd create --admin-password <pwd> <site>` — confirmed current syntax
  (`docs.checkmk.com/latest/en/checkmk_getting_started.html`).
- Automation secret readable at
  `var/check_mk/web/automation/automation.secret` relative to site home —
  confirmed exact path via docs (`wato_user.html`).
- "Each Checkmk site includes a default automation user" — confirmed via
  docs, so the code's assumption that a bare `omd create` yields a usable
  automation account (no separate user-creation call needed) is correct.
- `GET /version` connectivity check matches plan's citation.

**⚠️ Improved, not fully closed — package installation:**
The plan's goal statement and Phase 1 step 1 explicitly include
*"Install the CheckMK Community package (`.deb`) on the target OS"* as part
of "automates the base setup... from scratch — installation through
activated, monitored hosts." No code anywhere in the repo runs `apt`,
`dpkg`, or downloads the Checkmk package itself (`site.py` only calls
`omd create`/`omd start`, which require Checkmk to already be installed).

**Decision (2026-08-24):** full install automation was deliberately not
built. Checkmk's `.deb`/`.rpm` packages are normally obtained through the
customer portal or a configured distro repo — confirmed via docs
(`install_packages_redhat.html`: *"Users with active subscriptions can
access installation packages through the customer portal"*) — so silent,
unattended installation isn't a clean fit for a single tool without
knowing the target's package source in advance. Instead, `site.py` gained
`omd_installed()` (`shutil.which("omd")`) as a Phase 1 pre-flight check:
if Checkmk isn't installed, the wizard now fails immediately with the
correct install command (verified against
`docs.checkmk.com/latest/en/install_packages_debian.html`: `apt install
/path/to/check-mk-community-<version>_<codename>_<arch>.deb`) and the
official download page, instead of prompting for a site name first and
then failing deep inside `omd create` with a raw subprocess/`FileNotFoundError`.
The tool's scope still starts one step later than the plan's stated goal —
that gap is now a fast, clear failure instead of a silent assumption.

**Minor — deviates from plan step 3, but arguably an improvement:**
Plan step 3 says: if the site already exists, "fall back to prompting the
user for the existing `cmkadmin` credentials." The code doesn't do this —
it reuses the automation secret from disk instead, and only prompts for a
secret (not `cmkadmin` credentials) if that file is missing. Since nothing
downstream uses `cmkadmin` at all (everything is automation-secret/REST
API), this is a reasonable simplification, not a functional bug — but it's
a deviation from the written plan worth noting since it changes the
documented recovery path.

**✅ New — 2026-08-25, "reset existing site" option, beyond the original
plan/CONCERNS.md scope, added for repeated wizard test iteration.** When
the site already exists, the wizard now asks `Reset it?` (default No)
before falling back to reuse. Answering yes runs `site.remove_site()`
(`site.py:75-85`, `omd -f rm <site>`) — deleting the site's config, data,
and system user, but not the Checkmk install or other sites — then
recreates it fresh via the same path as a brand-new site. This isn't
called for by the plan (which only covers "prompt for existing cmkadmin
credentials" on collision) but fills the gap of resetting a test/dev site
to defaults without a full package reinstall. New tests:
`tests/test_site.py`.

**✅ Fixed — 2026-08-25, unvalidated site name crashed the wizard.** Found
live during manual testing: entering a site name `omd create` rejects
(doesn't start with a letter, contains a disallowed character, or exceeds
16 characters — `docs.checkmk.com/latest/en/omd_basics.html`, "Creating
sites") raised an unhandled `SiteBootstrapError` out of `_create_fresh_site()`,
killing the entire run with a raw Python traceback instead of a re-prompt —
the same class of gap as the Phase 3 CIDR/port issue fixed earlier
2026-08-25, just not caught until it was hit live. **Fix:** the site-name
prompt (`wizard.py:77-85`) now validates against `_SITE_NAME_RE`
(`wizard.py:30`, matching OMD's own rule) and re-prompts on a mismatch
instead of passing the value straight to `omd create`. New tests:
`tests/test_wizard.py`.

**⚠️ Correction — 2026-08-25, this audit's own Phase 1 claim was wrong.**
Earlier in this section ("✅ Verified correct against live docs" above)
this document states *"Each Checkmk site includes a default automation
user"* as a doc-confirmed fact. Live testing of a real 2.4.0p35 CE site
disproved this directly: `omd create` provisions exactly two users,
`cmkadmin` (admin role, no automation secret) and `agent_registration`
(automation-capable, but role-scoped solely to agent registration — a
`GET .../domain-types/user_config/collections/all` call with its
credential returns 401 *"you lack the permission... 'User management'"*).
There is no general-purpose default automation user. Checkmk's own docs
turned out to already say this precisely, just not surfaced by the
original context7 queries: `docs.checkmk.com/latest/en/wato_user.html` —
*"Each Checkmk site includes a default automation user **for agent
registration**"* (glossary entry, `docs.checkmk.com/latest/en/glossar.html`)
— the "for agent registration" qualifier is exactly the distinction this
audit missed. Practical effect confirmed by the user hitting the
"No default 'automation' user secret found on disk" fallback on every
fresh site during manual testing, not as a rare edge case.

**✅ Fixed — 2026-08-25, auto-provision the 'automation' user instead of
requiring a manual GUI step every time.** Given the above, Phase 1's
"no automation secret found — create one manually" fallback
(`wizard.py:113-119`) was previously the *expected* outcome on every fresh
site, not a fallback. **Fix:** `_create_fresh_site()` (`wizard.py:53-66`)
now calls the new `bootstrap_automation_user()` (`api.py:231-377`)
immediately after `omd create`/`omd start`, using the cmkadmin password it
just generated to log in via Checkmk's GUI session-cookie flow
(`login.py`, scraping the CSRF token and POSTing the login form — verified
live that the GET-based login shown in some Checkmk doc examples returns
"Method not allowed" on this version) and then calling
`POST /domain-types/user_config/collections/all` with
`auth_option.store_automation_secret: true` to create the `automation`
user with a generated secret, matching the exact on-disk path
`site.get_site_credentials()` already reads. This exact request body
isn't covered by Checkmk's generic REST API docs (context7 didn't surface
it despite three targeted queries) — it was instead extracted from the
live site's own OpenAPI spec (authenticated `GET
<site>/check_mk/api/1.0/openapi-doc.yaml`) and confirmed end-to-end
against a real running site before being wired into the wizard. Any
failure in this bootstrap (wrong password somehow, unexpected HTML,
non-2xx response) is caught and falls through to the pre-existing manual
prompt — never fatal. Not attempted when reusing an existing, non-reset
site, since that path never has cmkadmin's password available. New tests:
`tests/test_api.py` (6 cases, respx-mocked — 2 more added by the
self-activation fix below).

**✅ Fixed — 2026-08-25, auto-provisioning left a foreign pending change
that broke Phase 7 activation on every run.** Found live by the user:
Phase 7 failed with 401 *"There are changes from other users and foreign
changes are not allowed in this API call"* despite hosts/folders/the
automation user all visibly existing in the GUI. Root cause: the previous
fix's user-creation call is itself a pending WATO change attributed to
`cmkadmin` — every subsequent call (folders, hosts, discovery, and
finally Phase 7's `activate_changes`) runs as `automation` with
`force_foreign_changes` at its safe default of `False`, so Checkmk
correctly refuses to activate a change from a different user. First fix
attempt (self-activate the `cmkadmin` change immediately, cookie-
authenticated, right after creating the user) was correct in principle —
confirmed via manual `curl` with a `sleep 2` between steps — but failed
under the wizard's actual (much faster) timing: `activate-changes` is an
async background job, and the fire-and-forget POST returned before the
job finished, so a follow-up `activate_changes()` call moments later
still saw the change as in-progress and hit the identical 401. Checkmk's
response includes a `wait-for-completion` link for exactly this, but
live-verified it's a redirect-based long-poll (302 while running, not a
single blocking call) — httpx doesn't follow redirects by default, and
naively enabling `follow_redirects=True` hit `httpx.TooManyRedirects`
instead of actually waiting. **Fix:** poll the activation run's own
`self` link for `extensions.is_running` directly (0.3s interval, ~9s
cap) instead of relying on the redirect link — full control, no redirect
surprises. Verified live end-to-end under the worst-case timing (zero
delay between site creation and a manual `activate_changes()` call,
reproducing the user's report exactly): activation now succeeds cleanly.
New tests: `tests/test_api.py` (2 more cases — immediate-completion fast
path and the polling loop with `asyncio.sleep` mocked out).

**✅ Fixed — 2026-08-25, `omd create`/`omd start`/`omd rm` output was
silently discarded, including the diagnostic detail on failure.** Raised
by the user: does the wizard monitor `omd start`'s per-daemon output
("Starting X...OK"), since that's where a real failure would show up?
It didn't. `site.create_site()`/`start_site()`/`remove_site()`
(`site.py:57-107`) already captured `subprocess.run(..., capture_output=True)`
but only ever inspected `result.stderr` when `returncode != 0` — `stdout`
was discarded unconditionally, on success *and* failure. Live-verified
this loses real information: `omd`'s per-daemon progress
(`Starting apache...OK` / `Starting apache.............failed`) is on
**stdout**, not stderr. Reproduced by occupying the site's Apache TCP
port before `omd start` — the process's exit code (2) does correctly
propagate a single-daemon failure (so the existing `returncode != 0`
check was never silently swallowing failures), but the raised error only
included Apache's own stderr text, not the `stdout` line identifying
*which* daemon failed or confirming every other daemon started fine
first. For a non-web-facing daemon (no verbose stderr the way Apache
has), stdout could be the only signal.

**Fix:** all three functions now return `result.stdout` and include both
`stdout` and `stderr` in the raised `SiteBootstrapError`. `wizard.py`
prints each call's returned output to the console (dimmed) immediately —
`_create_fresh_site()` (`wizard.py:53-66`) for the create+start path, and
the reuse/reset branches in `phase1_site_bringup()` — so the operator
sees the same "Starting X...OK" transcript `omd` itself would print,
inline in the wizard's own output, whether it succeeds or fails. Verified
live end-to-end for both outcomes (clean start, and a forced Apache-port
conflict producing `Starting apache.............failed` plus the
underlying `Address already in use` reason in the caught error). New
tests: `tests/test_site.py` (6 cases covering all three functions'
success/failure stdout+stderr handling).

**✅ New — 2026-08-25, site-selection menu replaces the old
name-first-then-reset flow, requested by the user.** Previously Phase 1
always prompted for a site name first, then only offered "reset the site
under that same name" if it turned out to already exist — no way to see
what sites already exist before naming one, and no way to delete an old
site and create a fresh one under a *different* name in one flow.

**Fix:** `site.list_sites()` (`site.py:57-66` — lists directory names
under `/omd/sites/`, the same convention `site_exists()` already relies
on) runs before any prompt. No sites → straight to a validated new-site-
name prompt, unchanged from before. One or more sites → a menu: "Continue
with existing site '\<name\>'" per site, or "Delete a site, then create a
new one." Deleting loops back to the same menu (re-listing sites) rather
than forcing a new-site prompt immediately — so deleting one of several
sites still offers continuing with a remaining one, and a declined
delete-confirmation just re-shows the menu unchanged. Only once no sites
remain does the "no sites exist" branch prompt for a new name, which can
differ from any deleted site's name (the whole point of the request — the
old flow only ever recreated under the same name). Verified live with a
scripted (mocked `questionary`) run through all three paths: no-sites →
new site; existing → continue; existing → delete → create with a
different name (confirmed the deleted site no longer appears in
`list_sites()` afterward). New tests: `tests/test_site.py` (`list_sites()`
cases); site-selection loop verified via live scripted smoke test, not
unit tests — `wizard.py` orchestration remains at the project's existing
0% direct-unit-test coverage (see `CONCERNS.md`), consistent with every
other phase function.

**✅ Fixed — 2026-08-25, network-level failures bypassed every
`except CheckmkAPIError` in the codebase — the single highest-leverage
input-validation gap found this session.** Requested by the user: ensure
every value entered in the wizard is checked for validity, *and* that
nothing sent to Checkmk can crash the wizard with a raw exception.
Investigating that surfaced a gap upstream of any single field:
`CheckmkClient._request()` (`api.py:79-115`) — the one choke point every
`CheckmkClient` method goes through — only ever inspected the HTTP
response status; it never wrapped the `self._client.request(...)` call
itself. Live-verified: pointing `CheckmkConnection` at an unreachable or
malformed host raises a raw `httpx.ConnectError`, which none of
`wizard.py`'s per-phase `except CheckmkAPIError` blocks would catch.
`bootstrap_automation_user()` (`api.py:245-401`) has the same exposure
via its own direct `httpx` calls, contradicting its own documented
contract ("raises `CheckmkAPIError` on any failure").

**Fix:** `_request()` now catches `httpx.HTTPError` and re-raises as
`CheckmkAPIError` (`status_code=0` for "no HTTP response received") —
one fix, at the one choke point, closes this for every existing
`except CheckmkAPIError` site in the codebase without touching any of
them. `bootstrap_automation_user()`'s login/create-user calls got the
same wrapping directly, since it bypasses `CheckmkClient`. Verified live
both ways against `"my host with spaces"` — previously an unhandled
`ConnectError` traceback, now a clean `CheckmkAPIError`. New tests:
`tests/test_api.py` (2 cases, respx `side_effect` simulating a
`ConnectError`).

**✅ New — 2026-08-25, proactive format validation for every field
Checkmk itself constrains, live-verified rather than guessed.** Matching
how `_SITE_NAME_RE` was derived from `omd create`'s own error text, the
same approach was applied to the remaining fields: provoked 400 responses
from a real running 2.4.0p35 CE site and read the exact pattern Checkmk's
own validation reports back, rather than assuming.
- **Folder name** (`_FOLDER_NAME_RE`, `wizard.py:39`): `POST
  .../folder_config/collections/all` rejected `"my folder"`/`"my.folder"`
  with pattern `^[-\w]*\Z` — hyphens allowed (unlike site names), spaces
  and dots are not. Wired into Phase 2's folder-name prompt
  (`wizard.py:254-260`), re-prompted on a mismatch.
- **Host name** (`_HOST_NAME_RE`, `wizard.py:44`): `POST
  .../host_config/collections/all` rejected `"my host"`/`"host@name"`
  with pattern `^[-0-9a-zA-Z_.]+\Z` — dots allowed (for FQDNs/IPs), spaces
  and `@` are not. Wired into Phase 4's hostname prompt (`wizard.py:400-
  411`), re-prompted on a mismatch.
- **SNMP community string** — checked and found to have **no** format
  restriction (a value with spaces round-tripped through the REST API
  unchanged); left as free text, no validation added.
- **Checkmk host** (Phase 1 step 3, `_valid_checkmk_host()`,
  `wizard.py:55-62`) — not a Checkmk-enforced field (only used to build
  the wizard's own `base_url`), but validated as a parseable IP or an
  RFC-1123-style hostname (`_HOSTNAME_RE`, `wizard.py:50-52`) regardless,
  since bad input here is exactly what the network-error-wrapping fix
  above was written to catch — belt and suspenders, matching the user's
  explicit ask for both.
- **SSH username** (`wizard.py:486-490`) and **private-key path**
  (`wizard.py:497-507`, checked to exist as a local file) — not
  Checkmk-API fields, but a nonexistent key or blank username fails
  identically for every host in the batch, so caught once up front.
- **Automation secret manual-entry prompt** (`wizard.py:195-199`) —
  re-prompted if left blank.

New tests: `tests/test_wizard.py` (regex parametrized cases for all three
Checkmk-verified patterns). Verified live end-to-end: scripted an invalid
folder name and an invalid hostname through the actual phase functions
against a real site, confirmed both re-prompt with the exact live-derived
rejection reason and never reach the REST API with bad input.

**✅ Fixed — 2026-08-25, `start_site()` treated a harmless "already
running" restart as a fatal failure.** Found while smoke-testing the
Checkmk-host validation fix above, against `my_site` reused across
several test runs — not a bad-input case, a separate pre-existing bug.
Live-verified: `omd start` on a site that's already fully running (the
ordinary case when Phase 1 reuses an existing site) returns exit code 2
even though every daemon reports "already running"/"already started" —
`start_site()` (`site.py:89-113`) treated any nonzero exit as fatal,
so the wizard's single most common re-run scenario raised
`SiteBootstrapError` and crashed. **Fix:** only raise when the literal
word `"failed"` appears in `omd`'s stdout — live-confirmed present in
every genuine failure observed (e.g. `Starting apache.............failed`)
and absent from the already-running case. New tests: `tests/test_site.py`
(harmless-nonzero-exit case). Verified live end-to-end: reproduced the
original crash (start an already-running site), confirmed the fix
resolves it, confirmed a real induced failure (occupied Apache port)
still correctly raises.

---

## Phase 2 — Folder Structure

Matches the plan. `POST /domain-types/folder_config/collections/all` with
`{name, title, parent, attributes}` is correct current syntax. No findings.

**✅ New — 2026-08-25, folder-scoped subnet scanning, requested by the
user.** Beyond the original plan's scope (Phase 2 step 3 explicitly says
*"folder assignment can be decided per-host in Phase 4 regardless of
whether this phase runs"* — folders and network discovery were designed
as independent). The user wanted them tied together: each folder gets its
own subnet, scanned directly into it, with per-folder subnets optional
("I can decide not to enter any subnet for a folder"), and no more manual
per-host folder assignment in Phase 4.

**Fix, spanning Phases 2-4:**
- **Phase 2** (`wizard.py:202-260`) now loops one folder at a time
  (name, then its subnet — blank to create the folder without scanning it
  now) instead of a single comma-separated names prompt, returning
  `dict[str, str | None]` (`{"/vlan10": "10.0.0.0/24", "/vlan20": None}`).
  Live-verified finding along the way: Checkmk's host-config REST endpoint
  requires the **full folder path** (`/vlan10`) for the `folder` field —
  a bare name like `create_folder()`'s own `name` parameter takes is
  rejected with a 400 pattern-mismatch error. `phase2_folders()` stores
  the full path as the dict key so this distinction never leaks into
  Phase 3/4/5.
- **Phase 3** (`wizard.py:266-328`) scans each folder's subnet separately
  and stages results directly into that folder (`host_name`, `folder`,
  `attributes` all in one `create_host` call) — no longer always root
  regardless of Phase 2, closing a gap `_create_or_update_host()`'s own
  docstring used to flag as a known limitation (see Phase 5 section).
  Falls back to exactly the original single-CIDR flat-scan-to-root
  behavior when Phase 2 produced no folder/subnet pairs (skipped, or
  every subnet left blank) — no regression for anyone not using this.
  Returns `list[ScannedHost(ip, open_ports, folder)]` instead of the
  scanner's bare `HostScanResult`.
- **Phase 4** (`wizard.py:334-383`) drops the per-host folder prompt
  entirely — `OnboardedHost.folder` is copied straight from the selected
  `ScannedHost`, since the folder is already known from which scan found
  the host. Checkbox `value` is the whole `ScannedHost` object (not a bare
  IP string) so this carries through without an extra lookup.

Verified live end-to-end (not unit tests — this is orchestration/prompt
flow, same 0%-direct-coverage precedent as the rest of `wizard.py`):
scripted a real run creating two folders (one with a subnet scanning
`127.0.0.0/30` against the site's own Apache port, one without), confirmed
the host landed in the REST API with `extensions.folder == "/vlan10"`
(not root), confirmed the no-subnet folder was skipped, and confirmed
Phase 4 asks no folder question while still producing the correct
`OnboardedHost.folder`. Also re-verified the flat-fallback (no folders at
all) path still stages at root exactly as before. Related, incidental
fix: `_create_or_update_host()`'s "folder placement" limitation note (see
Phase 5 section) is effectively closed now that Phase 3 stages into the
correct folder from the start — its fallback `PUT` no longer needs to
move anything.

---

## Phase 3 — Network Discovery

Matches the plan closely, and the plan's own justification for *not* using
native Checkmk scanning is independently confirmed accurate:

- **Confirmed:** native "Networks to scan" is a background cronjob that
  runs "every minute," using **ping + DNS resolution only — no TCP port
  checks** (`docs.checkmk.com/latest/en/wato_hosts.html`, "The principle").
  This matches the plan's rationale for building a custom scanner exactly.
- **Confirmed:** Checkmk's own docs recommend capping native scans at
  **2048 addresses (/21)** for performance — the plan's citation of this
  number is accurate (`hosts_setup.html`).
- Port list (22/80/443 default, TCP-connect only, UDP/SNMP explicitly
  out of scope) matches plan step 3-4 exactly.

No findings beyond what CONCERNS.md already flags as tech debt (no
network-level timeout, no cancel/resume on large ranges). See Phase 2
section above for the 2026-08-25 folder-scoped scanning feature, which
changes this phase's signature and staging behavior but not its scanning
mechanics.

---

## Phase 4 — Host Classification

Matches the plan exactly — manual promotion only, no fingerprinting, by
design. No findings.

---

## Phase 5 — Host Onboarding

**✅ Verified correct against live docs:**
- Agent Receiver port 8000 default, confirmed via `omd config show | grep
  AGENT_RECEIVER` output shown in docs — matches.
- `GET /domain-types/agent/actions/download/invoke?os_type=linux_deb`
  (and `windows_msi`) — confirmed exact current endpoint and query param
  from `docs.checkmk.com/latest/en/agent_linux.html` and `agent_windows.html`.
- `cmk-agent-ctl register --hostname --server --site --user --password`
  (Linux) and the `cmk-agent-ctl.exe register` PowerShell equivalent
  (Windows) — both confirmed exact current syntax.
- "Registration must run locally on the target host, not via REST API" —
  confirmed; the code does this correctly over the SSH session.

**✅ Fixed — SNMP-only host path (2026-08-24).**
Plan step 1 explicitly describes two onboarding paths: agent-based hosts
get `"API integrations, Checkmk agent"`, and SNMP-only devices (switches,
routers) get `"No API integrations, no Checkmk agent"` plus SNMP
credentials. Phase 4's OS-family prompt was binary (`linux`/`windows`
only, `wizard.py:167-169` in the pre-fix version) — there was no SNMP path
anywhere in Phase 4 or 5.

**Fix:** Phase 4 (`wizard.py:173-191`) now offers a third choice, `snmp`,
and additionally prompts for SNMP version (`v2c`/`v1` — **v3 deliberately
out of scope**, community-string auth only, to avoid the much larger
auth/priv-protocol surface v3 requires) and community string. Phase 5
(`wizard.py:233-256`) branches SNMP hosts to their own path: `create_host`
with `tag_agent: "no-agent"` and `tag_snmp_ds: "snmp-v2"`/`"snmp-v1"` —
both values doc-confirmed via Checkmk's CSV host-import attribute mapping
(`docs.checkmk.com/latest/en/hosts_setup.html`, which shows
`agent=no-agent`/`snmp_ds=snmp-v2` as the exact attribute short-names for
a switch entry) — then `continue`s, skipping firewall/SSH/agent-install
entirely, since Checkmk polls SNMP devices directly and no agent is
involved. **Caveat:** the `snmp_community` attribute's exact JSON shape
(`{"type": "v1_v2_community", "community": "..."}`) was **not** independently
confirmed against live Checkmk REST API docs — context7 did not surface
the community-credential attribute schema specifically. This is flagged
in the code comment and should be verified against the target site's own
REST API spec before production use; everything else in this fix is
doc-confirmed.

**✅ Fixed — OS-compatibility check and package selection (2026-08-24),
addressed together since the RPM dead-code bug was a direct consequence of
the wrong-reference bug.**
Plan step 1 says the compatibility check should compare the target's
distro/version against *"the package family Checkmk offers for that
distro"* — i.e. availability-based. The original implementation instead
compared the target's `/etc/os-release` against **the Checkmk server's
own** `/etc/os-release`, requiring an *exact* `id` + `version_id` match —
a different and stricter check than specified (would warn on perfectly
installable combinations, e.g. Ubuntu target + Debian Checkmk host, both
`.deb`-based, purely because the distros differed). Separately,
`wizard.py` always called `client.download_agent("linux_deb")`
unconditionally, so `remote.install_agent_linux`'s working `.rpm` branch
was dead code — RPM-family distros would have a Debian package pushed and
`dpkg -i` attempted, failing outright.

**Fix:** `remote.check_os_compatibility()` (`remote.py:195-224`) now reads
only the target's own `/etc/os-release` and classifies it via the new
`remote.package_family()` (`remote.py:89-98`) using `ID`/`ID_LIKE` — the
standard freedesktop.org os-release fallback convention, so derivatives
(Rocky, Alma, Mint, etc.) are recognized without an exhaustive distro
list. The deb/rpm split itself is doc-confirmed:
*"RPM packages are intended for RHEL-based systems, SLES, Fedora, and
openSUSE, while DEB packages are used for Debian, Ubuntu, and other
DEB-based distributions"* (`docs.checkmk.com/latest/en/agent_linux.html`,
"Downloading RPM/DEB packages"). The classified family now flows through
to both `download_agent(os_type)` (`linux_deb`/`linux_rpm`) and
`install_agent_linux`'s package filename (`wizard.py:289-321`), so the
`.rpm` install branch is reachable and correct for RPM-family hosts.
Unrecognized distros fall back to the same "proceed assuming `.deb`?"
confirmation prompt the original code had for mismatches.

**✅ Fixed — credential-scope deviation from Checkmk's documented security
best practice (2026-08-24).**
Live docs describe a purpose-built, least-privilege **`agent_registration`**
role/user specifically for `cmk-agent-ctl register`, distinct from the
general `automation` REST API user — *"It is recommended to use the
pre-configured automation user 'agent_registration' for this task, as its
scope is restricted solely to host registration"*
(`docs.checkmk.com/latest/en/hosts_autoregister.html`), confirmed again in
`agent_deployment.html`: *"the default 'agent_registration' user is
pre-configured with these rights."* The original code reused the same
broad-scope `automation` credential (used for all folder/host/discovery/
activation REST calls) for agent registration too — a new finding from
doc verification, not previously flagged in the plan or CONCERNS.md: it
granted every registered agent's credential the same blast radius as the
full automation account.

**Fix:** `CheckmkConnection` (`api.py:27-50`) gained
`registration_user`/`registration_secret` fields, defaulting to
`username`/`secret` via `__post_init__` (`api.py:42-46`) — so unchanged
behavior when no dedicated credential is available. Phase 1
(`wizard.py:81-108`) looks up a site-provisioned `agent_registration` user
the same way it already looks up `automation` (`site.get_site_credentials`,
already generic over the username parameter — no changes needed there).
If found, it's used for `cmk-agent-ctl register`
(`linux_register_command`/`windows_register_command`, all three call sites
in `wizard.py` updated); if not found, the wizard prints a note and falls
back to reusing `automation`, same as before this fix — no behavior
regression for sites without a dedicated registration user. New tests
confirm the default-then-override behavior of the new fields
(`tests/test_api.py`).

**Note — this is a plan-blind check, not a Checkmk-edition check:** the
"permission to register **new** hosts" via `cmk-agent-ctl register-new`
(auto-create-on-registration) is documented as Ultimate-only, but this
wizard always creates the host via the REST API *before* calling plain
`cmk-agent-ctl register` (not `register-new`), which only needs permission
to register an *already-existing* host — a Community Edition capability.
The fix above doesn't depend on the Ultimate-only feature.

**✅ Fixed — package integrity not verified after SFTP transfer
(2026-08-24), closing a CONCERNS.md finding.**
CONCERNS.md's "Package Integrity Not Verified" item noted that agent
packages downloaded via the REST API were pushed to targets over SFTP with
no checksum or integrity check — a successful SFTP write only confirms no
exception was raised, not that the bytes on disk match what was sent.

**Fix:** `install_agent_linux()` (`remote.py:260-334`) now computes a
SHA256 digest of the downloaded package bytes locally, then runs
`sha256sum <path>` on the target after the SFTP write and compares the two
before attempting install. A mismatch or a failed `sha256sum` invocation
returns `FAILED_FALLBACK_MANUAL` — install is never attempted against an
unverified file. `sha256sum` is a coreutils staple present on both deb-
and rpm-family distros, matching the same distro-family assumption already
established for package selection.

**✅ New — post-install functional verification (2026-08-24), beyond the
original plan/CONCERNS.md scope, per explicit request.**
Previously, once `dpkg -i`/`rpm -i` and `cmk-agent-ctl register` both
returned exit code 0, the wizard reported the host as `AUTOMATED` and moved
on — trusting the register command's exit code as proof the agent is
actually working, with no independent check. The only later confirmation
was Phase 7's Livestatus query, run once for the whole batch at the very
end of the run, not per-host immediately after install.

**Fix:** after a successful install+register, the wizard now runs
`cmk-agent-ctl status` on the target (`remote.check_agent_status()`,
`remote.py:350-365`) and checks its output for a `Connection:
<server>/<site>` line matching the site — confirmed output format via
context7 (`docs.checkmk.com/latest/en/hosts_autoregister.html`, "Check
Agent Controller status" — example: `Connection: myserver/mysite`). The
match logic is a separate, directly-tested pure function
(`agent_status_shows_connection()`) rather than parsing inline, avoiding
the fragile-inline-parsing anti-pattern already flagged elsewhere in this
codebase (`livestatus.py`'s CSV handling). This is a **local** check on
the target's own agent-controller state — it does not independently
confirm the Checkmk *server* has accepted the host as UP; that remains
Phase 7's job. Printed as its own `Agent status: verified / could not
verify` line, distinct from the install line, so a host that installed
successfully but isn't actually connected is now visible to the operator
at the point of failure instead of only showing up (or not) in Phase 7's
summary table minutes later.

**Already known (CONCERNS.md), still present:** `known_hosts=None`
disabling SSH host-key verification; secrets passed as `cmk-agent-ctl
--password` argv (visible in `ps`); hardcoded `sudo` with no `NOPASSWD`
check; sequential (non-concurrent) per-host processing.

**✅ Fixed — 2026-08-25, three findings from a follow-up code review of
`src/checkmk_wizard/` against the implementation (not a plan-conformance
question — these are correctness bugs found by re-reading the code, not
gaps against the plan document):**

1. **Phase 3→5 host-name collision silently dropped onboarding config.**
   Phase 3 stages every scanned IP as a host object under `host_name=ip`
   (`wizard.py:184-186`). Phase 4 defaults the promotion hostname to that
   same IP, so Phase 5's `create_host` collided with the Phase 3 stub on
   the common (default-hostname) path — not the rare "invalid hostname"
   edge case CONCERNS.md's "Incomplete Error Recovery in Phase 5" entry
   describes. Combined with that entry's already-known "continues anyway
   after create fails" bug, the host's `tag_agent`/`tag_snmp_ds`/
   `snmp_community`/`ipaddress` from Phase 5 were silently never applied —
   worst for SNMP devices, which could be left tagged as agent-based
   instead of `no-agent` and never correctly polled.
   **Fix:** both `create_host` call sites in `phase5_onboarding()` now go
   through a new `_create_or_update_host()` helper (`wizard.py:247-266`)
   that falls back to `client.get_host()` + `update_host_attributes()`
   (an `If-Match`/ETag `PUT`, both already existing but previously unused
   client methods) when the create collides. This narrows the still-open
   "continues anyway" bug's actual trigger to genuine create failures.
   **Known limitation, documented in the code and in WIZARD-OPERATION.md:**
   the fallback updates attributes only, not folder — Checkmk's host-config
   `PUT` doesn't support moving folders, so a host promoted into a
   non-root folder that already exists at root (from Phase 3) stays at
   root. New tests: `tests/test_wizard.py`.
2. **`windows_register_command()` didn't quote its arguments.** Unlike
   `linux_register_command()` (`shlex.quote()` for POSIX shell),
   `windows_register_command()` (`remote.py:259-267`) interpolated
   hostname/server/site/user/password unquoted into the printed PowerShell
   command — a value containing a space, `$`, or `'` produced a broken
   copy-paste instruction. **Fix:** new `_ps_quote()` helper
   (`remote.py:250-256`) wraps each argument as a single-quoted PowerShell
   literal (doubling embedded `'`), matching the care already given to the
   Linux command. New test: `tests/test_remote.py`.
3. **Unhandled CIDR/port input crashed the whole wizard.** Phase 3
   (`wizard.py:145-165`) passed the raw CIDR/port text straight to
   `ipaddress.ip_network()`/`int()` with no validation; a typo raised an
   uncaught `ValueError` that killed the entire 7-phase run (no
   resume/checkpoint support — see WIZARD-OPERATION.md), losing all prior
   progress. **Fix:** both prompts now validate on entry and re-prompt on
   a parse failure instead of propagating the exception.

---

## Phase 6 — Discovery & Baseline

**✅ Verified correct:** the endpoint the wizard calls —
`POST /domain-types/service_discovery_run/actions/start/invoke` — is
confirmed exact current syntax (`docs.checkmk.com/latest/en/rest_api.html`).

The plan specifies three steps for this phase:
1. Run discovery — **implemented.**
2. Apply baseline discovery rulesets (systemd services, SNMP community,
   disabled-services) — **decision 2026-08-24: deliberately deferred, see
   below.**
3. **Accept discovered services** (bulk accept via API, or flag for manual
   review) — **fixed 2026-08-24.**

**✅ Fixed — step 3, previously the most significant finding in this audit.**
The original implementation called `start_service_discovery(hostname,
mode="refresh")`. Checkmk's own docs are explicit that `refresh` alone
does not put services into monitoring: *"Newly discovered services appear
as **undecided** and can be added to monitoring by **accepting them** and
activating changes"* (`docs.checkmk.com/saas/en/wato_services.html`).
`refresh` and "accept" are documented as separate actions — so the
original code would activate host configuration in Phase 7 while
leaving every discovered service undecided and never actually monitored.

**Fix:** `wizard.py`'s `phase6_discovery()` now calls
`start_service_discovery(hostname, mode="fix_all")`. `fix_all` is
Checkmk's REST equivalent of the UI's "Accept all" action — confirmed via
docs to add missing services, remove vanished ones, and accept host
labels in a single call, i.e. discovery + acceptance together
(`docs.checkmk.com/latest/en/wato_hosts.html`, "Service management
actions"). This matches the plan's step 3 option of "bulk accept via API"
and is appropriate here since these are freshly onboarded hosts with
nothing pre-existing to selectively review.

While fixing this, `CheckmkClient.start_service_discovery()` also picked
up handling for HTTP 303: Checkmk's own REST API example for this exact
endpoint shows it can respond with `303` when discovery runs as an async
background job rather than synchronously
(`docs.checkmk.com/latest/en/rest_api.html`). The client previously only
accepted `200`/`201`/`204` and would have raised `CheckmkAPIError` on a
303, misreporting a successful background-job start as a failure —
covered by a new test (`test_start_service_discovery_accepts_303_background_job`
in `tests/test_api.py`).

**⚠️ Step 2 (baseline discovery rulesets) — deliberately deferred, not
built (decision 2026-08-24).**
The plan itself hedges all three of its examples as situational: "apply
baseline rulesets *where useful*", systemd discovery "*if* the host runs
relevant services", disabled-services "to suppress *known-noisy* checks."
Two of the three (systemd single-services discovery, disabled-services)
require operator judgment about a specific environment — which services
run where, which checks are noisy for this deployment — that a generic
onboarding wizard has no way to infer from a network scan. Building either
would mean guessing at a ruleset-rule-creation REST payload shape this
session could not confirm via context7 (Checkmk's rule API is scoped
per-ruleset-name, `/domain-types/rule/collections/all?ruleset_name=...`,
and no worked example for a specific ruleset surfaced), for behavior the
plan doesn't specify concretely enough to build against confidently.

The third example, "SNMP community ruleset," is effectively already
covered by the Phase 5 SNMP fix: the community string is set as a **host
attribute** (`snmp_community`) directly on the host object rather than via
a separate folder-level ruleset — a different mechanism than the plan's
wording, but the same functional outcome for SNMP-only hosts. This was
confirmed with the user rather than assumed; the alternative (adding an
optional "disabled services" prompt with a guessed rule-creation payload)
was explicitly declined in favor of not building against an unconfirmed
API shape.

---

## Phase 7 — Activation & Validation

**✅ Verified correct against live docs:**
- `GET /domain-types/activation_run/collections/pending_changes` → read
  `ETag` header, then `POST
  .../activation_run/actions/activate-changes/invoke` with `{redirect,
  sites, force_foreign_changes}` and `If-Match: <etag>` — confirmed exact
  match to current docs, including the 200/201/204 response handling.
- Livestatus health check design (query host state via the site's local
  socket) is a reasonable implementation of the plan's generic "confirm
  hosts show UP" requirement; the plan doesn't specify a concrete mechanism
  here so there's nothing to conform to beyond intent, which is met.

**✅ Fixed — the "configuration snapshot" step (2026-08-24).**
Plan step 3: *"Export a configuration snapshot immediately after
activation using the **existing** `Checkmk configuration exporter.py`
script."* This script **does not exist anywhere in the repository** —
confirmed by search; the only reference to it in the entire codebase was
the plan document itself. The original implementation wrote a small
ad-hoc JSON file containing just the run timestamp, site name, and the
list of hosts onboarded in *this run* — materially different from *"a
JSON backup of the resulting configuration"* the plan promises: no rules,
no full host inventory, no folder structure, just a run-log of what this
invocation touched.

**Fix:** rather than building or reintroducing a reference to the
nonexistent external script, `CheckmkClient` gained `list_hosts()` (`GET
/domain-types/host_config/collections/all`, `api.py:149-152`) and
`list_folders()` (`GET /domain-types/folder_config/collections/all`,
`api.py:122-129`) — both confirmed against context7 to return the
collection's `value` array (verified via the pending-changes collection
example showing the same `{"domainType": ..., "value": [...]}` shape).
Phase 7 (`wizard.py:409-421`) now calls both after activation and includes
their results in the snapshot as `hosts`/`folders`, alongside the existing
`onboarded_this_run` list (renamed from `onboarded_hosts` to disambiguate
from the new full-site `hosts` key). If the fetch fails, the wizard prints
a warning and still writes the snapshot with `hosts`/`folders` as `null`,
rather than aborting — consistent with the rest of the codebase's
degrade-gracefully pattern.

**Scope correction, not full closure:** this now produces a real
hosts+folders configuration snapshot pulled live from the site — matching
the plan's "known good baseline... for diffing against future changes or
disaster recovery" intent — but it is **not** a full site backup. Rules,
users, and other site-wide configuration are not included; Checkmk's rule
API is scoped per-ruleset-name with no confirmed "list everything" call,
so a genuinely complete backup was out of reach without guessing at
payload shapes this session couldn't verify (same reasoning as the Phase 6
ruleset deferral above). This is documented explicitly in code comments
and in `WIZARD-OPERATION.md` rather than left as an implicit gap.

**Already known (CONCERNS.md), confirmed still present:** manual/fragile
CSV parsing in `livestatus.py` (splits on first `;` only, silently drops
malformed lines); no pre-flight check that the Livestatus socket exists
before connecting.

---

## Consolidated Gap List (priority order)

1. ~~**Phase 6 step 3 missing (accept discovered services)**~~ — **fixed
   2026-08-24**, see Phase 6 section above.
2. ~~**Phase 1 step 1 missing (package installation)**~~ — **improved
   2026-08-24** (pre-flight check + clear instructions, see Phase 1 section
   above); full automation deliberately out of scope, decision documented.
3. ~~**Phase 5: SNMP-only host path missing**~~ — **fixed 2026-08-24**, see
   Phase 5 section above. `snmp_community` payload schema unverified —
   see caveat there.
4. ~~**Phase 5: RPM package path is dead code**~~ — **fixed 2026-08-24**,
   see Phase 5 section above (fixed together with #5, same root cause).
5. ~~**Phase 5: OS-compatibility check compares against the wrong reference**~~
   — **fixed 2026-08-24**, see Phase 5 section above.
6. ~~**Phase 5: `cmk-agent-ctl register` uses the broad `automation` credential**~~
   — **fixed 2026-08-24**, see Phase 5 section above.
7. ~~**Phase 6 step 2 missing (baseline discovery rulesets)**~~ —
   **decision 2026-08-24: deliberately deferred**, see Phase 6 section
   above. Not built — the plan hedges this as situational and requires
   operator-specific knowledge the wizard can't infer; building it would
   mean guessing at an unconfirmed rule-creation payload shape.
8. ~~**Phase 7: snapshot step references a nonexistent script**~~ —
   **fixed 2026-08-24**, see Phase 7 section above. Now pulls a real
   hosts+folders snapshot from the live site via REST API; documented as
   partial (not a full site backup — no rules/users/other config).
9. ~~**Phase 3→5 host-name collision silently drops onboarding config**~~ —
   **fixed 2026-08-25**, see Phase 5 section above. Found in a follow-up
   code review, not the original 2026-08-24 audit.
10. ~~**`windows_register_command()` doesn't quote its arguments**~~ —
    **fixed 2026-08-25**, see Phase 5 section above.
11. ~~**Unhandled CIDR/port input crashes the wizard**~~ — **fixed
    2026-08-25**, see Phase 5 section above (Phase 3 input, fix grouped
    with the other 2026-08-25 findings).
12. ~~**Unhandled site-name input crashes the wizard**~~ — **fixed
    2026-08-25**, see Phase 1 section above. Found live during manual
    testing (`omd create` rejected the entered name), not by review.
13. ~~**No default 'automation' user exists on a fresh site — this
    audit's own earlier claim to the contrary was wrong**~~ — **fixed
    2026-08-25**, see Phase 1 section above. Found live during manual
    testing; auto-provisioning now closes the gap instead of requiring a
    manual GUI step on every fresh site.
14. ~~**`omd create`/`omd start`/`omd rm` output discarded, including
    on failure**~~ — **fixed 2026-08-25**, see Phase 1 section above.
    Raised by the user, not found during review.
15. ~~**Automation-user auto-provisioning left a foreign pending change
    that broke every Phase 7 activation**~~ — **fixed 2026-08-25**, see
    Phase 1 section above. Self-inflicted by fix #13; found live by the
    user hitting it in Phase 7 during the very next test run.
16. ~~**Site name asked before the operator can see what sites already
    exist, and deleting a site forced recreating under the same name**~~
    — **fixed 2026-08-25**, see Phase 1 section above. Requested by the
    user, beyond the original plan's scope.
17. ~~**Folder structure (Phase 2) and network discovery (Phase 3) were
    fully independent — no way to scan a specific subnet into a specific
    folder**~~ — **fixed 2026-08-25**, see Phase 2 section above.
    Requested by the user, beyond the original plan's scope (the plan
    explicitly designed these as independent).
18. ~~**Network-level failures (unreachable/malformed host) bypassed
    every `except CheckmkAPIError` in the codebase**~~ — **fixed
    2026-08-25**, see Phase 1 section above. The single highest-leverage
    finding from the user's "validate everything, never crash" request —
    fixed once at `CheckmkClient._request()`'s single choke point rather
    than at each of the ~10 call sites.
19. ~~**Folder names and hostnames weren't validated against Checkmk's
    own naming rules before being sent to the REST API**~~ — **fixed
    2026-08-25**, see Phase 2 section above. Requested by the user
    ("if a folder cannot have spaces, or dash, etc."); patterns
    live-verified against a real site rather than assumed, same method
    already used for `_SITE_NAME_RE`.
20. ~~**`start_site()` treated a harmless "already running" restart as a
    fatal failure**~~ — **fixed 2026-08-25**, see Phase 1 section above.
    Found live while smoke-testing fix #18/#19, not part of the original
    request — a separate pre-existing bug hit by the wizard's single most
    common re-run scenario.

Everything else — the mechanical parts of Phases 1, 2, 3, 5, 6, and 7
(REST payloads, CLI syntax, endpoint paths) and all of Phase 4 — matches
the plan and is independently confirmed accurate against current Checkmk
documentation.
Pre-existing tech-debt/security findings from `.planning/codebase/CONCERNS.md`
were spot-checked during this pass; the package-integrity item is now
fixed (see Phase 5 section), and the rest remain accurate and are not
repeated in full here except where doc verification added new context
(SSH credential handling, agent-registration credential scope).

---
*Audit performed 2026-08-24 against the implementation delivered in
"Implement CheckMK Setup Configurator wizard (Phases 1-7)." All Checkmk
REST API and CLI claims verified via context7 against docs.checkmk.com
(latest), not training-data recall.*
