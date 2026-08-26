# How the Wizard Works

Exact technical walkthrough of `checkmk-wizard` as implemented today. Every
claim below is traced to a file and line. For how this compares to the
original design, see [PLAN-CONFORMANCE-AUDIT.md](PLAN-CONFORMANCE-AUDIT.md).

## Prerequisites the wizard assumes are already true

- **Checkmk Community Edition is already installed** on the host (the `.deb`
  package). The wizard never installs it — see Phase 1 below.
- The wizard runs **locally on the Checkmk host**, as a user able to run
  `omd` and read `/omd/sites/<site>/...` (`site.py:30-31`).
- Python 3.11+, `uv`-managed environment (`pyproject.toml`).

## Entry point and control flow

`uv run checkmk-wizard` → `checkmk_wizard.__main__` → `wizard.main()`
(`wizard.py:1001-1002`) → `asyncio.run(run())` → `run()` (`wizard.py:989-999`),
which executes all 7 phases **sequentially, in a single process, with no
resume/checkpoint support**:

```
phase1_site_bringup()
  → CheckmkClient context manager opens
  → phase2_folders()
  → phase3_discovery()
  → phase4_classification()
  → phase5_onboarding()
  → phase6_discovery()
  → phase7_activation()
  → CheckmkClient context manager closes
```

State is passed by return value / parameter only — there is no persisted
state file. If the process is killed mid-run, the next run starts at Phase 1
with no memory of what happened before (site/hosts already created in
Checkmk are simply re-detected or re-created).

## Phase 1 — Site Bring-up (`wizard.py:127-250`)

1. **Pre-flight check:** `site.omd_installed()` (`site.py:44-46`) checks
   `shutil.which("omd")`. If Checkmk isn't installed at all, prints install
   instructions (`site.CHECKMK_NOT_INSTALLED_INSTRUCTIONS`, `site.py:31-41`
   — download link + `apt install` example) and `raise SystemExit(1)`
   immediately, before prompting for anything, rather than letting
   `omd create` fail later with a raw `FileNotFoundError`/subprocess error.
2. **Site selection** (`wizard.py:134-179`). `site.list_sites()`
   (`site.py:57-66` — lists directory names under `/omd/sites/`, the same
   convention `site_exists()` already uses) runs first, before any prompt:
   - **No sites exist:** goes straight to `_prompt_new_site_name()`
     (`wizard.py:113-123`) — same validation as before (`_SITE_NAME_RE`,
     `wizard.py:30`; must start with a letter, letters/digits/underscores
     only, max 16 characters, doc-verified:
     `docs.checkmk.com/latest/en/omd_basics.html`, "Creating sites";
     re-prompted on a mismatch instead of crashing `omd create` with an
     unhandled `SiteBootstrapError`) plus a not-already-taken check.
   - **One or more sites exist:** presents a menu — "Continue with
     existing site '\<name\>'" per site, plus "Delete a site, then create a
     new one" — via `questionary.select`.
     - Picking an existing site sets `reuse_existing = True` and moves on
       immediately.
     - Picking delete: asks which site if more than one exists, confirms
       (`questionary.confirm`, default **No** — destructive), then
       `site.remove_site()` and **loops back to the same menu** (so
       deleting one of several sites still offers "continue with a
       remaining one" before falling through to a new-site prompt; a
       cancelled/declined confirm also just re-shows the menu unchanged).
       Once no sites remain, the loop's "no sites exist" branch kicks in
       and prompts for a new name — which can differ from any deleted
       site's name, since site name is no longer asked before this
       decision.

     **Fixed 2026-08-25 — the "Delete a site..." choice used `value=None`,
     which silently broke the whole delete flow.** Live-verified bug,
     reported by the user (single site → picked delete → landed straight
     on the Checkmk-host prompt, no confirmation, no deletion output, no
     new-name prompt at all): `questionary.Choice.__init__`'s own default
     for its `value` parameter is *also* `None`, so passing `value=None`
     explicitly is indistinguishable from omitting it — `Choice` then
     falls back to using the **title string** as the value. Selecting
     "Delete a site, then create a new one" therefore returned that
     literal string as `selection`, which `if selection is not None:`
     treated as a real site name — skipping the delete/confirm/rename
     flow entirely and jumping straight to the host prompt with `site_name`
     set to that garbage string. A first reproduction attempt with a
     scripted (mocked-out `questionary.select`) test *passed*, because
     mocking `questionary.select` itself bypasses `Choice.__init__`
     entirely — the mock never resolves `.value` at all, so it can't catch
     a bug that lives inside that resolution. Only a test that constructs
     the real `Choice` and reads its real `.value` reproduces it. **Fix:**
     a dedicated sentinel object (`_DELETE_SITE`, `wizard.py:29`) instead
     of `None`, compared by identity (`is not _DELETE_SITE`). Verified
     live end-to-end against a real site: reproduced the exact reported
     symptom pre-fix, confirmed the fix resolves it (delete flow runs,
     new-name prompt appears, new site created). New tests:
     `tests/test_wizard.py` (constructs the real `questionary.Choice` and
     asserts `.value is _DELETE_SITE`, not the title string).
3. Prompts for **Checkmk host** (hostname/IP other systems use to reach
   this site; defaults to `localhost`) — same prompt as before, now asked
   once site selection is settled rather than up front. **Validated**
   (`_valid_checkmk_host()`, `wizard.py:59-66`) as either a parseable IP
   address or an RFC-1123-style hostname (`_HOSTNAME_RE`, `wizard.py:54-56`)
   and re-prompted on a mismatch. This isn't a Checkmk-enforced format —
   the value is only ever used to build the wizard's own `base_url` and
   printed into commands, never validated server-side — but bad input
   here (a stray space, an accidentally-included `http://` prefix, ...)
   used to reach `httpx` unvalidated and crash the wizard; see the
   `CheckmkClient._request()` fix below.
   - **New site:** `_create_fresh_site()` (`wizard.py:96-112`) generates a
     random admin password via `secrets.token_urlsafe(16)`, runs
     `omd create --admin-password <pwd> <site>` as a subprocess
     (`site.py:69-86`), then `omd start <site>` (`site.py:89-103`), then
     **prints the generated cmkadmin password to the console**. It then
     immediately calls `bootstrap_automation_user()` (`api.py:269-425`,
     see below) to auto-create the `automation` REST user using that
     cmkadmin password — best-effort: any failure there is caught, printed
     as a yellow warning, and falls through to the manual path in step 4.
   - **Existing site (reused):** just runs `omd start <site>` again
     (no-op if already running) and reuses the existing site's credentials
     below — no auto-provisioning attempt here, since that needs a
     cmkadmin password the wizard only knows right after it generates one
     itself.

   `create_site()`/`start_site()`/`remove_site()` all now **return their
   full stdout** (`site.py:69-129`), which the wizard prints to the
   console (dimmed) right after each call, and **include both stdout and
   stderr in the raised `SiteBootstrapError`** on a nonzero exit. Live-
   verified this matters: `omd`'s per-daemon progress
   (`Starting apache...OK`, or `Starting apache.............failed` on
   failure) is on **stdout**, not stderr, and was previously silently
   discarded on success and *dropped from the error entirely* on failure
   — only `stderr.strip()` was surfaced. Reproduced live by occupying the
   site's Apache TCP port before `omd start`: the process's exit code (2)
   correctly propagates a single-daemon failure, but without this fix the
   operator would only have seen the raw Apache stderr text, not which
   daemon failed or that every other daemon started fine first.

   **`start_site()` (`site.py:89-113`) also doesn't treat every nonzero
   exit as failure.** Live-verified: `omd start` on a site that's
   **already fully running** — the ordinary case when reusing an existing
   site (step 3's "Existing site (reused)" branch above) — also returns
   exit code 2, even though every daemon just reports "already
   running"/"already started". Before this fix, the wizard's single most
   common re-run scenario (start an already-started site) raised
   `SiteBootstrapError` and crashed. `omd`'s stdout is the only signal
   available to tell a genuine failure apart from this: every observed
   real failure includes the literal word "failed"; the already-running
   case never does — so `start_site()` only raises when `"failed"` appears
   in stdout, regardless of exit code.
4. `site.get_site_credentials(site_name)` (`site.py:145-149`) reads
   `/omd/sites/<site>/var/check_mk/web/automation/automation.secret`
   directly off disk.
   - **If found:** used as-is — no user prompt. This is now the common
     case for a fresh/reset site, since step 3's auto-provisioning writes
     this exact file (`auth_option.store_automation_secret: true` in the
     REST create-user call) before this step runs.
   - **If not found** (auto-provisioning wasn't attempted — reused an
     existing site — or it failed): prints instructions to create an
     `automation` user manually via the web UI and prompts for the secret
     interactively — re-prompted if left blank (`wizard.py:207-211`).
5. Separately, looks up a **dedicated `agent_registration` credential**
   the same way (`site.get_site_credentials(site_name,
   automation_user="agent_registration")`, `wizard.py:105`) — Checkmk ships
   this as a separate pre-configured, least-privilege user scoped solely to
   host registration (doc-verified: `docs.checkmk.com/latest/en/
   agent_deployment.html`). If found, it's kept separate from the REST
   credential and used only for `cmk-agent-ctl register` in Phase 5.2; if
   not found, prints a note and Phase 5.2 falls back to reusing the general
   `automation` credential (no prompt — silent, doc-explained fallback).
6. Builds a `CheckmkConnection(host, site, username, secret,
   registration_user, registration_secret)` (`api.py:27-50`) — `base_url`
   becomes `http://<host>/<site>/check_mk/api/v1`.
   `registration_user`/`registration_secret` default to `username`/`secret`
   via `__post_init__` (`api.py:42-46`) when no dedicated credential was
   found (or when constructed without them, e.g. in tests).
7. Opens a `CheckmkClient` and calls `GET /version` (`api.py:119-121`). On any
   `CheckmkAPIError`, prints the error and `raise SystemExit(1)` — **this is
   the only phase whose failure is fatal to the whole run.**

**Nothing in this phase installs the Checkmk package itself** — step 1
only *checks* that it's already installed and fails fast with guidance if
not; the rest of the phase creates/starts the OMD *site* inside an
already-installed Checkmk.

**Why step 3's auto-provisioning exists:** contrary to this project's own
earlier documentation (see `PLAN-CONFORMANCE-AUDIT.md`, Phase 1, 2026-08-25
entry), a fresh Checkmk site does **not** ship a general-purpose
`automation` user by default — live-verified on a real 2.4.0p35 CE site,
`omd create` only provisions `cmkadmin` (admin, not automation-capable)
and `agent_registration` (automation-capable, but scoped solely to agent
registration — insufficient for folders/hosts/discovery/activation). So
the REST credential this wizard needs for everything after Phase 1 had no
default account to read from disk; `_create_fresh_site()` now closes that
gap itself instead of leaving it to a manual GUI step every single time.

**How `bootstrap_automation_user()` works** (`api.py:269-425`) — the only
place in this codebase that authenticates any other way than Bearer +
automation secret, because none exists yet at this point:
1. `GET .../check_mk/login.py`, scrape the `global_csrf_token` JS variable
   out of the HTML.
2. `POST` the same URL as a login form (`_username=cmkadmin`,
   `_password=<the password just generated>`, `_login=1`,
   `filled_in=login`, `_origtarget=index.py`, `_csrf_token=<scraped>`) —
   confirmed live that GET-based login (shown in some Checkmk doc
   examples) returns "Method not allowed" on this version; only the full
   form POST works. Success is detected by the presence of an
   `auth_<site>` cookie in the client's cookie jar afterward.
3. `POST .../check_mk/api/v1/domain-types/user_config/collections/all`
   using that session cookie (Checkmk's REST API accepts Bearer, Cookie,
   or Webserver auth) with `{username: "automation", fullname: ...,
   auth_option: {auth_type: "automation", secret: <generated>,
   store_automation_secret: true}, roles: ["admin"]}`. `admin` role
   matches `CHECKMK_SETUP_CONFIGURATOR_PLAN.md`'s own stated fallback
   ("Administrator is acceptable for a single-operator setup tool") —
   there's no built-in role scoped for general folder/host/discovery/
   activation access short of admin.
4. **Self-cleanup activation.** Step 3 is itself a pending WATO change
   attributed to `cmkadmin` (this session), not to the new `automation`
   user. Left un-activated, the first later call to
   `CheckmkClient.activate_changes()` — authenticated as `automation`,
   `force_foreign_changes` at its safe default of `False` — fails with
   401 *"There are changes from other users and foreign changes are not
   allowed in this API call."* Live-verified: `GET pending_changes` right
   after user creation shows exactly one entry, `user_id: cmkadmin`,
   `action_name: edit-users`. `bootstrap_automation_user()` fetches its
   ETag and `POST`s `activate-changes/invoke` for it immediately, still
   authenticated as `cmkadmin` activating its own change (no
   foreign-changes issue). Activation runs as an async background job
   (`is_running: true` in the immediate response) — a naive
   fire-and-forget here left a real race live-verified against this same
   site: a folder/host create moments later followed by an immediate
   `activate_changes()` call could still see the `cmkadmin` change as
   in-progress and hit the same 401. Checkmk's response also includes a
   `wait-for-completion` link, but live-verified it's a redirect-based
   long-poll (302 while running) rather than a single blocking call —
   httpx doesn't follow redirects by default, and naively following them
   hit `httpx.TooManyRedirects` rather than actually waiting. Instead,
   `bootstrap_automation_user()` polls the activation run's own `self`
   link for `extensions.is_running` (0.3s interval, 30 attempts ≈ 9s
   cap) until it reports done. Best-effort throughout step 4: any
   failure (including a poll timeout) is swallowed, not raised — the
   `automation` user from step 3 is already created and usable either
   way; worst case, the next `activate_changes()` call hits the same
   foreign-changes error this wizard had before auto-provisioning
   existed, no worse off.

None of this request-body shape is covered by Checkmk's generic REST API
docs (context7 doesn't surface it) — it was instead verified against a
live site's own OpenAPI spec (`<site>/check_mk/api/1.0/openapi-doc.yaml`,
reachable once authenticated) and confirmed end-to-end against a real
running 2.4.0p35 CE site: login → create user → Bearer-auth with the new
secret → `automation.secret` file appears on disk at the path
`site.read_automation_secret()` already reads.

## Phase 2 — Folder Structure (`wizard.py:257-390`; `_network_scan_attributes` at `wizard.py:257-280`, `phase2_folders` at `wizard.py:285-390`)

**Changed 2026-08-25: folders now carry their own subnet, one at a time,**
instead of a single comma-separated names list with no subnet concept.
Returns `dict[str, str | None]` — `{"/vlan10": "10.0.0.0/24", "/vlan20":
None, ...}` — an empty dict (Phase 2 skipped, or every folder's subnet
left blank) signals Phase 3 to fall back to a single flat scan into the
root folder, same as the wizard's original behavior.

1. `questionary.confirm` — "Set up folders?" Defaults to **No**. If no,
   returns `{}` immediately.
2. If yes, loops one folder at a time until an empty name is entered:
   - **Folder name** (blank finishes the loop). A leading `/` is stripped
     if typed, then **validated** (`_FOLDER_NAME_RE`, `wizard.py:43`) and
     re-prompted on a mismatch — live-verified against a real Checkmk site
     (see below) that only letters, digits, underscores, and hyphens are
     allowed; a name with a space or dot is rejected before it ever
     reaches `create_folder()`.
   - **Subnet/CIDR for this folder** (blank = create the folder but don't
     scan it in Phase 3) — validated the same way as Phase 3's old
     single-CIDR prompt (`ipaddress.ip_network(..., strict=False)`,
     re-prompted on a parse failure).
   - Creates the folder via `POST /domain-types/folder_config/collections/all`
     with `{name, title, parent: "/", attributes: {tag_agent: "no-agent",
     tag_snmp_ds: "no-snmp"}}` (`api.py:125-137`). Failures are printed and
     don't stop the loop.
   - **Inert-by-default folder attributes (2026-08-26):** `tag_agent:
     "no-agent"`/`tag_snmp_ds: "no-snmp"` are baked into the `create_folder`
     call itself (unlike Network Scan below, these two tag groups are
     foundational Checkmk tag groups — always present, so no separate
     failure-isolated call is needed). Any host that lands in this folder —
     including one created outside this wizard's control entirely, e.g. by
     the folder's own Network Scan below — **inherits these as its
     effective attributes** unless the host itself sets something
     different (live-verified: a bare host created with only `ipaddress`
     shows `tag_agent: "no-agent"`/`tag_snmp_ds: "no-snmp"` under
     `effective_attributes` on `GET .../host_config/{name}?effective_attributes=true`).
     Without this, Checkmk's own implicit default is `tag_agent: "cmk-agent"`
     ("API integrations if configured, else Checkmk agent") — which falsely
     implies a host is already being monitored via agent before anyone has
     configured one. Phase 3 and Phase 5 (below) set these explicitly, per
     host, once a host's real monitoring method is known — explicit
     host-level attributes always win over the folder default.
   - **Network Scan setup (2026-08-26, `wizard.py:_network_scan_attributes`,
     `phase2_folders` lines 358-377):** if a subnet was given *and* the
     folder was created, a **second, independent** call configures
     Checkmk's own built-in per-folder Network Scan — a background cronjob
     Checkmk runs on its own schedule, distinct from this wizard's
     one-time Phase 3 scan — so hosts added to the network *after* the
     wizard finishes keep getting found without re-running it. Deliberately
     a separate `GET` (for the ETag) + `PUT update_attributes` call rather
     than folding it into the `create_folder` POST above: a network-scan
     validation failure (e.g. a site missing the standard "criticality" tag
     group) must never take the folder itself down with it. Payload
     (live-verified against a real Checkmk 2.4.0p35 CE site via its
     OpenAPI schema, `NetworkScan`/`IPNetwork` components):
     `{addresses: [{type: "network_range", network: <normalized CIDR>}],
     time_allowed: [{start: "00:00", end: "23:59"}], scan_interval: 86400,
     tag_criticality: "offline"}`. `tag_criticality: "offline"` ("Do not
     monitor this host") means newly-found hosts land in host
     administration unmonitored, for manual review — mirrors this wizard's
     own Phase 3 (stage) → Phase 4 (promote) split rather than
     auto-monitoring unclassified hosts. Live-verified: the scan only
     creates hosts for IPs not already configured anywhere on the site, so
     it never touches or duplicates hosts already onboarded by this
     wizard. Skipped (with a yellow note) for a non-IPv4 CIDR — Checkmk's
     `network_scan.addresses` field is IPv4-only — and any other failure
     here is caught and printed, never blocking the folder itself.
   - Records `folder_subnets[f"/{name}"] = cidr_or_None` — the **full
     path** (`/vlan10`), not the bare name `create_folder()` takes.
     Live-verified this distinction matters: Checkmk's host-config REST
     endpoint validates `folder` against a path pattern
     (`^(?:(?:[~/]|(?:[~/][-\w]+)+[~/]?)|[0-9a-f]{32})$`) and rejects a
     bare name like `"vlan10"` with a 400 error — caught by the same live
     smoke test that verified the rest of this feature. Storing the full
     path here means Phase 3/4/5 never need to know about the distinction.
3. If no folders end up with a subnet (including "no folders at all"),
   prints a note that Phase 3 will fall back to a single flat scan.

## Phase 3 — Network Discovery (`wizard.py:391-467`)

**Changed 2026-08-25: scans each Phase 2 folder's subnet directly into
that folder**, instead of a single subnet always staged at root
regardless of Phase 2. Falls back to exactly the original single-CIDR
flow when Phase 2 produced no folder/subnet pairs.

1. Builds `scans: list[(folder, cidr)]` from the non-empty entries in
   Phase 2's `folder_subnets`; folders with no subnet are listed
   ("Skipping scan for folder(s) with no subnet given: ...") and simply
   don't get a scan.
2. **If `scans` is empty** (Phase 2 skipped, or every subnet was left
   blank): prompts for a single CIDR exactly as before (validated,
   re-prompted on a parse failure) and scans it into the root folder `/`
   — unchanged fallback behavior for anyone not using folder-scoped
   scanning.
3. Prompts **once** for the port list (default `22,80,443` —
   `scanner.py:17`), shared across every folder's scan — validated,
   re-prompted on a parse failure, same as before.
4. For each `(folder, cidr)` pair, runs `scan_network()` (`scanner.py:63-85`
   — CIDR chunked into `/24`s, bounded-concurrency TCP-connect sweep, a
   host counts as "alive" if any checked port responds) and **stages every
   alive IP directly into that folder**: `POST
   /domain-types/host_config/collections/all` with `{host_name: ip,
   folder: folder, attributes: {ipaddress: ip, tag_agent: "no-agent",
   tag_snmp_ds: "no-snmp"}}` (`wizard.py:438-450`, `api.py:168-182`) — no
   longer always root. `tag_agent`/`tag_snmp_ds` set explicitly here
   (2026-08-26) rather than relying on the Phase 2 folder default above —
   the root-fallback path (step 2, no Phase 2 folders at all) has no
   folder object of this wizard's own to carry that default, so every
   staged host declares its own inert state regardless of which folder it
   lands in. Failures are printed and skipped, not retried.
5. Renders one combined `rich` table (IP / Folder / Open ports) across all
   folders' results after every scan completes, then returns
   `list[ScannedHost(ip, open_ports, folder)]`.

## Phase 4 — Host Classification (`wizard.py:469-556`)

Purely interactive — **no API calls, no fingerprinting, and (changed
2026-08-25) no folder prompt** — each host's folder is already known from
which Phase 2 folder-subnet scan found it (`/` for the flat-fallback
case):

1. Presents a checkbox list of scanned hosts — `<ip> [<folder>] (ports:
   ...)` — via `questionary.checkbox`, `value` set to the whole
   `ScannedHost` object (not just the IP string), so the folder travels
   with the selection without a separate lookup.
2. For each selected host: prompts for hostname (default = the IP,
   **validated** against `_HOST_NAME_RE` (`wizard.py:49` — live-verified
   against a real Checkmk site: `POST .../host_config/collections/all`
   rejected "my host"/"host@name" with pattern `^[-0-9a-zA-Z_.]+\Z`) and
   re-prompted on a mismatch
   (`wizard.py:487-498`) and a monitoring-method choice — `linux` (agent),
   `windows` (agent), or `snmp` (no agent — switches/routers/printers/etc.)
   (`questionary.select`, `wizard.py:499-506`).
3. **If `snmp`:** additionally prompts for SNMP version (`v2c` or `v1` —
   **v3 is not supported**, community-string auth only) and the community
   string (default `public`) (`wizard.py:508-517`).
4. **Expected-open ports (2026-08-26, `wizard.py:519-543`):** for every
   host regardless of `os_family`, prompts for a comma-separated list of
   "expected-open" ports to monitor going forward — defaults to whatever
   Phase 3's scan actually found open on that IP (a reasonable starting
   guess, editable/clearable), re-prompted if any value falls outside
   1-65535. Blank means none. Phase 5 turns each one into a Checkmk
   `active_checks:tcp` ("Check TCP port connection") rule scoped to that
   host — a real monitored service that goes CRITICAL if the port stops
   responding (e.g. an internal service on that host crashed). This is
   only the "should stay open" direction; the inverse ("alert if a port
   that should stay closed — e.g. RDP — opens up") has no equivalent
   native Checkmk option (its `active_checks:tcp` only lets you configure
   the state for a *refused* connection, never for a *successful* one —
   confirmed by reading the check's actual ruleset source shipped on the
   Checkmk install) and isn't implemented here yet; it would need a
   classical active check wrapping `check_tcp` in the Monitoring Plugins
   `negate` wrapper. Deferred — revisit if wanted.
5. Returns a list of `OnboardedHost(ip, hostname, folder, os_family,
   snmp_version, snmp_community, expected_open_ports)` — `folder` copied
   straight from the selected `ScannedHost`, never asked interactively.

## Phase 5 — Host Onboarding (`wizard.py:698-867`)

Runs once for the whole batch, then loops **sequentially, one host at a
time** — no concurrency.

**Setup (once):**
1. Asks "Attempt automated SSH firewall + agent install for Linux hosts?"
   (default Yes).
2. If yes: prompts for SSH username (re-prompted if left blank,
   `wizard.py:712-715`), then auth mode (password or private key path) →
   builds one `SSHCredentials` object reused for **every** Linux host in
   the batch (same username/credential for all hosts). A private-key path
   is checked to exist as a local file (`Path(...).expanduser().is_file()`,
   `wizard.py:722-733`) and re-prompted if not — not a Checkmk-API
   validation, but a nonexistent key would fail identically for every
   host in the batch, so this is caught once up front rather than once
   per host inside `asyncssh`'s own connection error handling.

**Host create/update (`_create_or_update_host()`, `wizard.py:562-585`):**
Both branches below go through this helper instead of calling
`client.create_host()` directly. Phase 3 already staged every scanned IP
as a bare host object under `host_name=ip` **in the folder its scan
belongs to** (see Phase 3 above); a Phase 4 promotion that keeps the
default hostname (== IP) therefore always collides with that stub host on
`create_host`. The helper catches the resulting `CheckmkAPIError`, fetches
the existing host's ETag (`client.get_host()`), and `PUT`s the attributes
via `update_host_attributes()` instead — so `tag_agent`/`tag_snmp_ds`/
`snmp_community`/`ipaddress` still land on the host rather than being
silently dropped by the failed create. **Note:** this fallback only
updates attributes, not folder placement — Checkmk's host-config `PUT`
doesn't support moving folders — but since Phase 3 now stages each host
directly into its real target folder (2026-08-25; previously always
root), `folder` here already matches what Phase 3 used, so this
limitation no longer bites in practice. A create/update failure for any
other reason (e.g. an invalid hostname) still just prints a warning and
the wizard **continues anyway** to the firewall/SSH steps regardless
(known bug — see audit) — this fix narrows that bug's trigger to genuine
failures, since the common IP-collision case no longer fails at all.

**IP-placeholder cleanup on rename (2026-08-26, `wizard.py:680-692`):** If
Phase 4 gave a host a hostname different from its scanned IP, the Phase 3
stub (`host_name=ip`, inert `tag_agent: "no-agent"`/`tag_snmp_ds:
"no-snmp"`) is a leftover, separate object from the new `host_name=hostname`
object about to be created below — the collision-fallback above only
kicks in when the hostname *equals* the IP, so a rename previously left
both visible in Checkmk side by side. Before creating/updating the named
host, the wizard now calls `client.delete_host(ip)`
(`api.py`, `DELETE /objects/host_config/{name}`, live-verified against a
real Checkmk 2.4.0p35 CE site: 204 with no `If-Match`/ETag required) and
swallows `CheckmkAPIError` (e.g. 404 if Phase 3 never staged it) —
best-effort, never blocks onboarding.

**Expected-open-port rules (`_create_expected_open_port_rules()`,
`wizard.py:588-610`):** called right after a successful host create/update,
for **both** branches below — once per port in `h.expected_open_ports`
(Phase 4). Each call is `client.create_rule(ruleset="active_checks:tcp",
folder=h.folder, value_raw=<JSON dict {port, svc_description}>,
conditions={host_name: {match_on: [h.hostname], operator: "one_of"}})`
(`api.py`, `POST /domain-types/rule/collections/all`). Live-verified
end-to-end against a real Checkmk 2.4.0p35 CE site: the rule survives
activation and Phase 6's discovery picks it up as a real monitored
service named `TCP Port <N> (expected open)`, going CRITICAL if that port
stops responding. `value_raw` is sent as plain JSON (confirmed Checkmk
accepts this, not only the Python-repr-with-single-quotes form its own
"export for API" GUI feature produces). Only inside the `try` block, so a
failed host create/update skips rule creation entirely; each port's own
`CheckmkAPIError` is caught individually so one bad port never blocks the
rest of that host's ports or the wider onboarding loop. Deliberately only
the "should stay open" direction — see the note in Phase 4 above for why
the inverse ("alert if a normally-closed port opens") isn't implemented.

**Per host:**
1. **If `os_family == "snmp"`:** `_create_or_update_host(host_name=hostname,
   folder=..., attributes={ipaddress, tag_agent: "no-agent", tag_snmp_ds:
   "snmp-v2"|"snmp-v1", snmp_community: {type: "v1_v2_community",
   community}})` (`wizard.py:703-713`) — no firewall/SSH/agent steps at
   all, `continue` to next host. `tag_agent`/`tag_snmp_ds` values are
   doc-verified (Checkmk's CSV host-import attribute mapping,
   `docs.checkmk.com/latest/en/hosts_setup.html`); the `snmp_community`
   payload shape is best-effort and **not** independently doc-confirmed —
   verify against the target site's own REST API spec before relying on it.
2. **Otherwise:** `_create_or_update_host(host_name=hostname, folder=...,
   attributes={ipaddress, tag_agent: "cmk-agent", tag_snmp_ds: "no-snmp"})`
   (`wizard.py:779-784`). `tag_snmp_ds` set explicitly here (2026-08-26,
   same reasoning as Phase 3's staging) rather than left to Checkmk's own
   default for that tag group.
3. **Systemd/Windows service monitoring (2026-08-26, `wizard.py:788-796`):**
   for both non-SNMP branches (windows and linux alike — ahead of the
   windows/linux `continue` split below, not inside either arm of it), asks
   which specific systemd units / Windows services should be *actively*
   monitored, then configures Checkmk's discovery to pick them up:
   - **`_collect_expected_services()` (`wizard.py:618-644`):** for a Linux
     host with SSH credentials available, tries a **live SSH scan**
     (`remote.list_running_systemd_services()`, `remote.py:151-179` —
     `systemctl list-units --type=service --state=running --no-legend
     --plain` over the same SSH connection used for firewall/install
     above) and presents the result as a `questionary.checkbox` so the
     user picks from what's *actually running*, rather than guessing
     spelling. Falls back to a manual comma-separated
     `questionary.text` prompt (blank = skip) for: a Windows host (this
     wizard never establishes any remote connection to Windows hosts —
     same manual-by-design scope as agent install), a Linux host with no
     SSH credentials, or a scan that came back empty (unreachable, or
     the command failed). Stored on `h.expected_services` — Phase 6
     reads it back to verify (see below).
   - **`_create_service_discovery_rules()` (`wizard.py:648-694`):** one
     rule covering *all* requested names at once (unlike the TCP-port
     rules above — this ruleset's name-list field natively holds
     multiple entries) — `discovery_systemd_units_services` for Linux,
     `inventory_services_rules` for Windows, scoped by the same
     `host_name` condition pattern as the TCP-port rules. The exact
     regex construction here is the product of live debugging against a
     real Checkmk 2.4.0p35 CE site (installed the real agent on a real
     systemd host to get ground truth, then read the shipped
     check-plugin source), not assumption — two non-obvious findings
     that would otherwise silently discover **zero** services with no
     error anywhere in the pipeline:
     - Systemd: a bare (non-`~`-prefixed) name entry requires an
       **exact** string match, not a regex — every entry is sent
       `~`-prefixed here to always get regex matching.
     - Systemd: Checkmk's own agent-side parser **strips the trailing
       `.service` suffix** from the unit name before matching a
       discovery rule against it (confirmed by reading
       `_parse_name_and_unit_type()` in the shipped
       `cmk/plugins/collection/agent_based/systemd_units.py`) — a rule
       built from the raw `"apache2.service"`
       form matches nothing. `_create_service_discovery_rules()` strips it
       (`name.removesuffix(".service")`) before building the regex, for
       exactly this reason.
     - Windows (`inventory_services_rules`'s `services` list): every
       entry is *always* treated as a regex already — no `~` prefix
       needed or supported there.
     Both platforms' entries are anchored `^...$` and `re.escape()`d so a
     name matches exactly, never as an accidental prefix of a different
     service. Best-effort: a failure here is caught and printed, never
     blocking the rest of onboarding.
4. **If `os_family == "windows"`:** prints
   `windows_firewall_instructions()` and `windows_register_command()`
   (`remote.py:194-198, 293-301`) as copy-paste text, using
   `connection.registration_user`/`registration_secret` (not
   `username`/`secret` — see credential-scope note below). No automation
   attempted at all for Windows — `continue` to next host.
   `windows_register_command()` PowerShell-quotes each argument
   (`_ps_quote()`, `remote.py:284-290` — single-quoted literal, doubled
   embedded `'`) so a hostname/site/password containing a space, `$`, or
   `'` still produces a valid command to copy-paste; `linux_register_command`
   already did the POSIX-shell equivalent via `shlex.quote()`.
5. **If `os_family == "linux"`:**
   a. `remote.probe_port(ip, 8000)` (`remote.py:119-139`) — TCP connect
      attempt to the Agent Receiver port; classifies as `open`,
      `closed_rst` (got `ConnectionRefusedError`), or `filtered_or_down`
      (timeout/other OSError). Result is printed, **not acted on** —
      informational only.
   b. If no SSH credentials were supplied: prints manual firewall/install
      instructions (`_print_linux_manual`, `wizard.py:868-873`) and moves
      to the next host.
   c. Otherwise, `remote.fix_firewall_linux(ip, creds, 8000)`
      (`remote.py:201-236`):
      - `check_ssh_reachable()` first; if it fails →
        `FAILED_FALLBACK_MANUAL`.
      - Over one SSH connection, runs `command -v ufw`, then
        `command -v firewall-cmd`, then `command -v nft` (first match
        wins, in that fixed order) to pick a backend.
      - Runs `sudo <backend-specific allow rule>` unconditionally
        (`sudo ufw allow 8000/tcp`, etc.) — **no confirmation prompt, no
        dry-run, no rollback.**
      - Any failure → `FAILED_FALLBACK_MANUAL` with the manual rule text.
   d. `remote.check_os_compatibility(ip, creds)` (`remote.py:239-268`):
      reads `/etc/os-release` over SSH on the target and classifies it as
      `deb`-family or `rpm`-family via `remote.package_family()`
      (`remote.py:93-102`), using the target's own `ID`/`ID_LIKE` — **not**
      a comparison against the Checkmk host's own OS. Doc-verified against
      `docs.checkmk.com/latest/en/agent_linux.html` ("RPM packages are
      intended for RHEL-based systems, SLES, Fedora, and openSUSE, while
      DEB packages are used for Debian, Ubuntu, and other DEB-based
      distributions"). If the distro isn't recognized as either family,
      shows a warning and asks "Proceed anyway assuming .deb?" (default
      **No**).
   e. If the user chose not to proceed, skips agent install for that host
      and continues to the next.
   f. `register_cmd = remote.linux_register_command(hostname, host, site,
      connection.registration_user, connection.registration_secret)`
      (`wizard.py:840-842`) — uses the dedicated `agent_registration`
      credential from Phase 1 when one was found, **not** the general
      `automation` REST credential (see credential-scope note below).
   g. `client.download_agent(os_type)` (`api.py:211-218`) — requests
      `linux_deb` or `linux_rpm` based on the package family determined in
      step d (defaults to `linux_deb` if the compatibility check itself
      couldn't run, e.g. SSH became unreachable between steps).
   h. `remote.install_agent_linux(ip, creds, package_bytes,
      package_filename, register_cmd)` (`remote.py:303-377`), where
      `package_filename` is `check-mk-agent.deb` or `check-mk-agent.rpm`
      to match the package family from step g:
      - SFTP-uploads the package to `/tmp/<package_filename>` on the
        target.
      - **Verifies the upload with a checksum** (`remote.py:328-347`):
        runs `sha256sum <path>` on the target and compares it to a
        `hashlib.sha256` of the bytes sent — a successful SFTP write only
        means no exception was raised, not that what landed on disk
        matches what was sent, so this catches silent truncation/
        corruption before attempting install. Mismatch or a failed
        `sha256sum` call → `FAILED_FALLBACK_MANUAL`, install is not
        attempted.
      - Installs with `sudo dpkg -i <path>` or `sudo rpm -i <path>`
        (chosen by filename suffix — both branches are now reachable).
      - Runs `sudo cmk-agent-ctl register --hostname ... --server ...
        --site ... --user <registration_user> --password ...` (the
        `register_cmd` built in step f) **on the target host over the same
        SSH connection** (registration must run locally on the monitored
        machine, not via REST API).
      - Any step failing → `FAILED_FALLBACK_MANUAL` with manual
        instructions; success → `AUTOMATED`.
   i. **If install returned `AUTOMATED`:** `remote.check_agent_status(ip,
      creds, site)` (`remote.py:393-408`, `wizard.py:862-865`) runs
      `cmk-agent-ctl status` on the target and checks (via
      `agent_status_shows_connection()`, `remote.py:380-390`) that its
      output contains a `Connection: <server>/<site>` line for this site —
      confirming the agent controller is actually operational and recorded
      a connection, rather than trusting the register command's exit code
      alone. Doc-verified output format:
      `docs.checkmk.com/latest/en/hosts_autoregister.html`, "Check Agent
      Controller status". This is a **local** check on the target only —
      it doesn't independently confirm the Checkmk server accepted the
      host as UP; that's confirmed later, for the whole batch, by Phase 7's
      Livestatus query. Printed as its own `Agent status: verified /
      could not verify` line, separate from the install line.

## Phase 6 — Discovery & Baseline (`wizard.py:879-937`)

For every onboarded host: `POST
/domain-types/service_discovery_run/actions/start/invoke` with
`{host_name, mode: "fix_all"}` (`api.py:222-234`) — discovers services and
accepts them (adds missing, removes vanished, accepts host labels) in one
call, so services are actually in the monitored state by the time Phase 7
activates changes. A `303` response (Checkmk ran discovery as an async
background job) is treated as success, not an error.

**Verifies expected-service discovery (2026-08-26, `_verify_expected_services()`,
`wizard.py:895-936`):** right after each host's `mode="fix_all"` call, if
that host has `expected_services` (set in Phase 5, see above), checks the
discovery response's `check_table` for each requested name and prints a
per-service ✓/✗. This exists because a discovery-selection rule whose
name/regex doesn't match anything raises no error anywhere in this
pipeline — it just silently discovers zero matching services (live-verified
the hard way while building this feature: an unstripped `.service` suffix
produced no error, just nothing found), so success can't be assumed and
must be checked. Looks for `f"Systemd Service {name}"` / `f"Service {name}"`
among entries whose discovery `value` is `"monitored"` (distinct from
`"active"`, which is what TCP-port active-check services show instead —
live-verified these are different phase labels for different check
categories). If `discovery_result` is falsy (the `303`
background-job case, where `start_service_discovery()` returns `{}`),
prints a "could not verify" note instead of a false failure, since there's
no `check_table` to check yet in that case.

**Deliberately not implemented (decision 2026-08-24, revised 2026-08-26):**
applying a baseline "disabled-services" discovery ruleset (silencing
known-noisy default checks). Still deferred — the plan's language hedges
this as situational ("known-noisy checks") requiring operator judgment
about a specific environment the wizard has no way to infer from a scan.
(This decision originally also covered "systemd services" baseline
discovery — that part is now implemented, see Phase 5's "Systemd/Windows
service monitoring" above and this phase's verification step.) The plan's
third example, an "SNMP community ruleset," is effectively already covered:
Phase 5 sets the SNMP community as a **host attribute** directly
(`snmp_community`) rather than via a separate folder-level ruleset object —
a different mechanism than the plan's wording, but the same outcome
(SNMP-only hosts get their community string configured).

## Phase 7 — Activation & Validation (`wizard.py:939-988`)

1. `GET /domain-types/activation_run/collections/pending_changes` to read
   the `ETag` header (`api.py:238-243`).
2. `POST /domain-types/activation_run/actions/activate-changes/invoke` with
   `{redirect: false, sites: [site], force_foreign_changes: false}` and
   `If-Match: <etag>` (`api.py:245-261`). On failure, prints the error and
   **returns early — the snapshot step below does not run.**
3. If there are onboarded hosts, queries Livestatus directly:
   - Connects to the UNIX socket `/omd/sites/<site>/tmp/run/live`
     (`livestatus.py:14-15`).
   - Sends the raw LQL query `GET hosts\nColumns: name state\nOutputFormat:
     csv\nColumnHeaders: off\n\n` and reads the socket until EOF.
   - Parses each line by splitting on the **first** `;` only
     (`line.partition(";")`, `livestatus.py:51`).
   - Maps state `0→UP`, `1→DOWN`, `2→UNREACHABLE`, anything else →
     `"unknown"`, and prints a table.
4. Pulls the site's **actual current** host/folder configuration —
   `client.list_hosts()` → `GET /domain-types/host_config/collections/all`
   and `client.list_folders()` → `GET
   /domain-types/folder_config/collections/all` (`api.py:184-187,
   139-146`; `wizard.py:969-975`) — rather than only logging what this run
   touched. Both return the collection's `value` array (doc-confirmed
   response shape: `docs.checkmk.com/latest/en/rest_api.html`,
   pending-changes collection example). If this fetch fails, prints a
   warning and writes the snapshot anyway with `hosts`/`folders` set to
   `null`, rather than aborting.
5. Writes a JSON file `config_snapshot_<YYYYMMDD_HHMMSS>.json` to the
   **current working directory** (wherever the wizard was launched from)
   containing `generated_at`, `site`, `onboarded_this_run` (this run's
   onboarding list — hostname/ip/folder/os_family, plus
   snmp_version/snmp_community **in plaintext** for SNMP hosts), and now
   also `hosts`/`folders` (the site's full current configuration from step
   4). **Scope note:** this covers hosts and folders only — rules, users,
   and other site-wide config are not included, so it's a partial
   configuration snapshot, not a full site backup.

## Key data structures

| Type | File | Purpose |
|---|---|---|
| `CheckmkConnection` | `api.py:27-50` | host/site/username/secret + computed `base_url`; `registration_user`/`registration_secret` default to `username`/`secret` via `__post_init__` |
| `CheckmkClient` | `api.py:56-261` | async context-managed `httpx` wrapper; one method per endpoint used |
| `WizardState` | `wizard.py:87-90` | declared but **unused** — phases pass state via direct return values/params instead |
| `HostScanResult` | `scanner.py:22-29` | IP + open ports — `scan_network()`'s own return type, wrapped into `ScannedHost` per folder by Phase 3 |
| `ScannedHost` | `wizard.py:70-73` | `HostScanResult` + which Phase 2 folder its subnet scan found it in (`/` for the flat-fallback case) — Phase 3's actual return type since 2026-08-25 |
| `OnboardedHost` | `wizard.py:77-90` | ip/hostname/folder/os_family (+ snmp_version/snmp_community if SNMP, expected_open_ports) from Phase 4; `folder` copied from `ScannedHost`, never prompted; `expected_services` set in Phase 5 instead (needs SSH access) |
| `ActionResult` | `remote.py:54-57` | outcome (`automated`/`manual_required`/`failed_fallback_manual`) + detail + manual text |
| `SSHCredentials` | `remote.py:41-44` | username + password or private key path, held in memory only |
| `OSRelease` | `remote.py:61-79` | parsed `/etc/os-release` (id, version_id, id_like) |
| `CompatibilityCheck` | `remote.py:106-110` | target OS + classified package family (`deb`/`rpm`/`None`) — not a same-OS-as-host comparison |
| `AgentStatusCheck` | `remote.py:114-116` | `verified: bool` + `detail: str` from post-install `cmk-agent-ctl status` check |

## Error-handling model

- Phase 1 pre-flight check (Checkmk not installed): **fatal**
  (`SystemExit(1)`, before any prompts).
- Phase 1 REST check failure: **fatal** (`SystemExit(1)`).
- Site bootstrap (`omd create`/`omd start`/`omd rm`, the last only on an
  explicit reset) failure: **fatal** (unhandled `SiteBootstrapError`).
- Everything else (folder create, host create, firewall, agent install,
  discovery start): **caught and printed, execution continues** — the
  wizard never aborts the whole run over a single host/folder failure.
- Livestatus socket errors in Phase 7: **unhandled** (bare exception
  propagates if the socket is missing/unreadable).

**Fixed 2026-08-25 — network-level failures used to bypass every
`except CheckmkAPIError` in the codebase.** `CheckmkClient._request()`
(`api.py:79-115`, the single choke point every `CheckmkClient` method —
`get_version`, `create_folder`, `create_host`, `start_service_discovery`,
`activate_changes`, all of them — goes through) only ever inspected the
HTTP response status; it never wrapped the `self._client.request(...)`
call itself in a `try`. Live-verified this matters: pointing
`CheckmkConnection` at an unreachable/malformed host raises a raw
`httpx.ConnectError`, not `CheckmkAPIError` — and **every** `except
CheckmkAPIError` block in `wizard.py` (one per phase) would miss it,
crashing the wizard with an unhandled traceback instead of the clean
red-message-and-exit (or print-and-continue) each of those call sites was
designed to do. This was the single highest-leverage input-validation gap
in the whole wizard: any bad-but-unvalidated field that made it into a
REST call, or a target simply being unreachable, hit this same hole.

**Fix:** `_request()` now catches `httpx.HTTPError` and re-raises as
`CheckmkAPIError` (`status_code=0` signals "no HTTP response was ever
received") — one fix, at the one choke point, closes the gap for every
existing `except CheckmkAPIError` site without touching any of them.
`bootstrap_automation_user()` (`api.py:269-425`) talks to `httpx`
directly rather than through `CheckmkClient`, so it needed the same fix
applied separately around its login/create-user calls, to keep its own
documented contract ("raises `CheckmkAPIError` on any failure") actually
true. Verified live both ways (a connection through `CheckmkClient` and
through `bootstrap_automation_user()` against `"my host with spaces"`)
now raise `CheckmkAPIError` cleanly instead of a raw `ConnectError`. New
tests: `tests/test_api.py` (2 cases, respx `side_effect` simulating a
`ConnectError`).

## Credential handling

- SSH password/private-key path lives only in the in-memory
  `SSHCredentials` dataclass for the duration of the run — never written to
  disk.
- The Checkmk automation secret and generated cmkadmin password are printed
  to the console (`rich` output) — visible in scrollback/terminal capture.
- SSH host key verification is disabled (`known_hosts=None`,
  `remote.py:143`) for every connection.
- The registration credential (`connection.registration_secret` — the
  dedicated `agent_registration` secret when found, otherwise the same
  `automation` secret used for REST calls) is passed as a `--password`
  command-line argument to `cmk-agent-ctl register` over the SSH session
  (`remote.py:271-281`), visible to anything reading that process's argv
  on the target host. Using the narrower `agent_registration` credential
  when available (Phase 1, `wizard.py:97-111`) limits what this exposure
  can be used for, compared to leaking the full `automation` credential.
- The SNMP community string (Phase 4, `snmp` hosts) is prompted in plain
  text via `questionary.text` (not password-masked) and later written
  unmasked into the Phase 7 `config_snapshot_*.json` file on disk — no
  worse than the existing automation-secret/cmkadmin-password console
  exposure noted above, but adds a second plaintext-on-disk credential
  path not present before this bundle of fixes.
- `bootstrap_automation_user()` (`api.py:269-425`) sends the freshly
  generated cmkadmin password over the login form (`_password=...`) and
  receives a session cookie back — both over plain HTTP by default
  (`CheckmkConnection.proto` defaults to `"http"`), same exposure profile
  as every other REST call this wizard already makes locally to
  `localhost`. It generates its own automation secret in memory
  (`secrets.token_urlsafe(24)`) and never prints it — it's picked up from
  the `automation.secret` file the create-user call writes to disk, same
  path/mechanism as any other site-provisioned automation user.

---
*Traced against commit implementing Phases 1–7 of the wizard, 2026-08-24.*
