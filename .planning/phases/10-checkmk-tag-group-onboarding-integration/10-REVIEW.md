---
phase: 10-checkmk-tag-group-onboarding-integration
reviewed: 2026-09-11T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - scripts/mqtt_poller.py
  - scripts/probe_checkmk_rest_shapes.py
  - scripts/smoke_test_poller.py
  - src/checkmk_wizard/api.py
  - src/checkmk_wizard/wizard.py
  - tests/test_api.py
  - tests/test_mqtt_poller.py
  - tests/test_wizard.py
  - deploy/compose.yaml
  - docs/Podman setup for checkmk, minio, mosquitto, worker.md
findings:
  critical: 6
  warning: 11
  info: 3
  total: 20
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-09-11
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 10's three moving parts were reviewed against baseline `58aa5f5`: the `device_type`
host tag group (api.py + wizard.py), per-host device-type/alias threading through Phase 4/5,
and the poller's REST-sourced folder/alias enrichment (mqtt_poller.py, compose.yaml).

Baseline hygiene is good: `uv run pytest -q` is 348 passed, and `uvx ruff check --no-cache`
on the changed files reports only the 3 pre-existing findings named in the phase brief
(1 B023 in `wizard.py`, 2 in `tests/test_wizard.py` — verified present at `58aa5f5`).
**No new lint findings.** The deliberate decisions listed in the phase brief
(`extract_device_type` bare-key-only, create-once tag group, backfill counting, `.env`
indirection) were confirmed as implemented-as-decided and are not reported.

The defects are concentrated in error paths and cross-entry-point consistency, not in the
happy path the tests cover:

- **Stack startup is now broken on a first-time deployment** (CR-01): Compose variable
  interpolation is a whole-file operation, so `${CMK_REST_SECRET:?...}` blocks `checkmk`
  and `mosquitto` from starting too — yet the secret it demands only exists *after* a wizard
  run against a running site. The docs describe a bootstrap order the compose file forbids.
- **The tag-group provisioning helper violates the contract in its own docstring** (CR-02):
  its `get_host_tag_group()` call sits *outside* the `try`/`except CheckmkAPIError`, so any
  transient REST failure propagates out of `phase2_folders` and — since `run()` wraps no
  phase — aborts the whole wizard run. Only the POST failure path has a test.
- **A failed tag-group provisioning silently breaks all host onboarding** (CR-03): Phase 5
  sends `tag_device_type` unconditionally with no success flag threaded from Phase 2, so if
  provisioning warned-and-continued, every `create_host` is rejected and the wizard reports
  N per-host warnings instead of one root cause.
- **`--once` was not updated for folder enrichment** (CR-04) and publishes blank-folder
  retained payloads over correct ones.
- **`--help` on the new probe script prints the live automation secret** (CR-05).
- **The crash-loop fix is only half a fix** (CR-06): `_normalise_restored_node` backfills
  missing keys but not wrong *types*, so a retained payload with a non-string `id` still
  raises an uncaught `TypeError` — reproduced locally.

The `folder=""` sentinel is also overloaded three ways (root folder / host absent from the
REST map / REST fetch never succeeded), which makes the new `check_device_enrichment` smoke
check fail with a misleading diagnosis on the most common deployment shape (WR-03).

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: `${CMK_REST_SECRET:?}` blocks the entire stack from starting, creating a bootstrap deadlock

**File:** `deploy/compose.yaml:177`
**Issue:** Compose variable interpolation with the `:?` error operator is evaluated when the
*whole file* is parsed, not lazily per-service. With `deploy/.env` absent, `podman compose up -d
checkmk` and `podman compose up -d mosquitto` both fail, not just `poller`. That is a hard
chicken-and-egg: the `automation` secret this variable demands does not exist until
`bootstrap_automation_user()` has run against a **live** site (as `deploy/.env.example:5-9`
and the new docs paragraph both state), and the site cannot be started to create it.

The docs assert the narrower, incorrect behaviour: *"Compose refuses to start the `poller`
service with a clear message if `CMK_REST_SECRET` is unset"*
(`docs/Podman setup for checkmk, minio, mosquitto, worker.md:144`). A first-time operator
following §3/§4 in order hits a wall on step one with an error naming a service they have not
reached yet.

**Fix:** Drop the `:?` guard and let the poller detect the missing credential at runtime
(it already degrades gracefully — see WR-05 for adding an explicit startup warning), or ship a
`deploy/.env.example`-derived default so the file parses:

```yaml
      # Empty default keeps the whole stack parseable before the automation
      # user exists; the poller logs a clear warning and degrades `folder`
      # to "" until deploy/.env is filled in (see §3).
      - CMK_REST_SECRET=${CMK_REST_SECRET:-}
```

and correct the docs paragraph. Verify with:
`cd deploy && env -u CMK_REST_SECRET podman compose config --services`.

### CR-02: `_ensure_device_type_tag_group`'s GET is outside its own try/except and aborts the whole wizard run

**File:** `src/checkmk_wizard/wizard.py:687-696`
**Issue:** The function's docstring promises *"Wrapped in `try`/`except CheckmkAPIError` and
printing a warning on failure rather than propagating ... a missing tag group must not abort a
wizard run mid-flight."* The implementation does not do that — the `try` starts *after* the
GET:

```python
    resp = await client.get_host_tag_group(DEVICE_TYPE_TAG_GROUP_ID)   # <-- unguarded
    if resp.status_code == 200:
        ...
        return
    try:
        choices = _load_device_types()
```

`get_host_tag_group` uses `expect=(200, 404)`, so any *other* outcome — 401 (stale secret), 403,
500, or a connectivity failure normalised to `CheckmkAPIError(status_code=0)` by `_request` —
raises. `phase2_folders` does not catch it, and `run()` wraps no phase
(`src/checkmk_wizard/wizard.py:2024` calls `phase2_folders(client)` bare), so a single transient
REST blip kills a run that has already completed Phase 1 site bringup. This directly contradicts
the codebase's documented warn-and-continue convention for best-effort provisioning.

The existing test only mocks a 404 GET + 400 POST
(`tests/test_wizard.py:1234-1243`); the GET-failure path is untested.

**Fix:** Move the GET inside the guarded block:

```python
    try:
        resp = await client.get_host_tag_group(DEVICE_TYPE_TAG_GROUP_ID)
        if resp.status_code == 200:
            console.print("[green]device_type tag group already present[/green] — skipping creation.")
            return True
        choices = _load_device_types()
        ...
    except CheckmkAPIError as exc:
        console.print(f"[yellow]could not provision device_type tag group: {exc}[/yellow]")
        return False
```

Add a regression test mocking the GET as `Response(500)` and asserting no raise.

### CR-03: A failed tag-group provisioning makes every Phase 5 host create fail, with no root-cause report

**File:** `src/checkmk_wizard/wizard.py:696-698` (warn-and-return) and `1597`, `1616-1621`,
`1632-1637` (unconditional attribute injection)
**Issue:** `_ensure_device_type_tag_group` returns `None` on both success and failure, so Phase 5
has no way to know the tag group does not exist. All three `_onboard_hosts` branches
nevertheless splice `**_device_type_and_alias_attributes(h)` — i.e. `tag_device_type` — into
every `create_host` body. Checkmk rejects an attribute referencing a non-existent tag group with
a 400, which `_create_or_update_host` turns into a `CheckmkAPIError`, which each branch catches
and prints as `host create/update: ...`.

Net effect: one transient failure in Phase 2 causes **zero hosts to be onboarded** in Phase 5,
reported as N identical per-host warnings with the real cause scrolled off-screen many prompts
earlier. This is strictly worse than the pre-Phase-10 behaviour, where a Phase 2 problem could
not affect host creation at all.

**Fix:** Thread the provisioning outcome and omit the tag when it is unavailable:

```python
async def _ensure_device_type_tag_group(client: CheckmkClient) -> bool:
    ...  # return True on present-or-created, False on any failure

def _device_type_and_alias_attributes(host: OnboardedHost, *, tag_group_available: bool) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    if tag_group_available:
        attrs[f"tag_{DEVICE_TYPE_TAG_GROUP_ID}"] = host.device_type
    if host.alias:
        attrs["alias"] = host.alias
    return attrs
```

and print one explicit warning in Phase 5 ("device_type tag group missing — hosts will be
created without a device type") rather than N opaque 400s.

### CR-04: `--once` never fetches folders, overwriting correct retained topology with blank folders

**File:** `scripts/mqtt_poller.py:1144-1165`
**Issue:** Phase 10 added the per-cycle REST folder lookup to `run_forever` only. The `--once`
branch of `main()` calls `query_devices(...)` with no `folders=` argument:

```python
            snapshots = query_devices(
                config.livestatus_host,
                config.livestatus_port,
                columns,
                DEFAULT_LIVESTATUS_TIMEOUT_SECONDS,
            )   # <-- folders= omitted; every snapshot.folder == ""
        ...
        run_cycle(client, config, state, snapshots)
```

`query_devices` then degrades every host to `folder=""`. `run_cycle` publishes
`lan/devices/{id}/status` (retain=True) with blank folders and — because `folder` participates
in `topology_signature` and `reconcile_state` restored the *correct* folders from the retained
topology — computes a signature difference and republishes `lan/devices/topology` (QoS 1,
retain=True) with every folder blanked.

`--once` is documented as the manual-verification path ("Run exactly one poll cycle then exit,
for manual verification"), so the tool an operator reaches for to check enrichment is the tool
that destroys it. It also makes `--once` immediately followed by `check_device_enrichment`
report the WR-05 "missing CMK_REST_SECRET" failure on a perfectly configured stack.

**Fix:** Mirror `run_forever`'s enrichment in the `--once` branch:

```python
        folders: dict[str, str] = {}
        try:
            folders = fetch_host_folders(
                cmk_rest_base_url(config),
                config.cmk_rest_username,
                config.cmk_rest_secret,
                DEFAULT_REST_TIMEOUT_SECONDS,
            )
        except RestError as exc:
            _logger.warning("Folder enrichment unavailable for this one-shot cycle: %s", exc)
        snapshots = query_devices(..., folders=folders)
```

Add a test asserting the `--once` path passes a non-empty `folders` mapping through to
`query_devices`.

### CR-05: `probe_checkmk_rest_shapes.py --help` prints the live automation secret in cleartext

**File:** `scripts/probe_checkmk_rest_shapes.py:337` + `343`
**Issue:** The parser is built with `formatter_class=argparse.ArgumentDefaultsHelpFormatter`,
which appends `(default: <value>)` to every argument's help text. `--rest-secret`'s default is
the *live secret*:

```python
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        ...
    parser.add_argument("--rest-secret", default=os.environ.get("CMK_REST_SECRET", ""))
```

Running `python3 /scripts/probe_checkmk_rest_shapes.py --help` inside the poller or worker
container — where `CMK_REST_SECRET` is set by `deploy/compose.yaml` — prints the Checkmk
automation user's secret to stdout, where it lands in terminal scrollback, shell transcripts,
CI logs and `podman logs`. The script goes to visible effort elsewhere to avoid exactly this
(`_redact_auth_header`, the `PollerConfig.__repr__` masking in the poller), so this is a gap in
an otherwise-deliberate secret-hygiene posture.

**Fix:** Do not let argparse render the secret's default. Either drop the formatter class, or
resolve the env var after parsing:

```python
    parser.add_argument(
        "--rest-secret",
        default=None,
        help="Automation secret. Defaults to $CMK_REST_SECRET (value never echoed).",
    )
    ...
    rest_secret = args.rest_secret or os.environ.get("CMK_REST_SECRET", "")
```

Apply the same treatment to `--rest-username` if it is ever considered sensitive.

### CR-06: `_normalise_restored_node` backfills missing keys but not wrong types — the crash-loop class is still open

**File:** `scripts/mqtt_poller.py:832-846` (and `parse_topology_payload:805-809`,
`topology_signature:358-371`)
**Issue:** The fix's own comment states the goal is that a cross-version or otherwise
unexpected retained payload "must fall back to a cold start, not crash-loop a
`restart: unless-stopped` container (T-09-05)". The normaliser only supplies defaults for
*absent* keys; it never checks the type of a key that is present. Reproduced locally against
the current file:

```
[{'id': 'a', 'parents': 'router1'}]  -> signature ('a', ('1','e','o','r','r','t','u'), ...)  # garbage
[{'id': 'a', 'alias': 5}]            -> signature ('a', (), 'unknown', '', 5)                 # non-str in signature
[{'id': ['x']}]                      -> CRASH TypeError: unhashable type: 'list'
```

The third case is an uncaught `TypeError` raised inside `parse_topology_payload`'s dict
comprehension (`node["id"]: ...`), on the *reconciliation* path, from a retained message that is
re-read on every restart — precisely the crash-loop the fix was written to close. A non-string
`alias` or `device_type` additionally risks a `TypeError` inside `sorted()` when it is compared
against a well-typed sibling node.

Note the inconsistency: `query_devices` (lines 605, 611, 619-620) *does* type-check the
equivalent Livestatus fields with `isinstance` before use. The deserialisation boundary the
comment identifies as "the single place where version skew enters" is the one boundary that
does not.

**Fix:** Coerce types, not just presence, and skip nodes that cannot be keyed:

```python
def _normalise_restored_node(node: dict) -> dict:
    parents = node.get("parents")
    return {
        **node,
        "parents": [p for p in parents if isinstance(p, str)] if isinstance(parents, list) else [],
        "device_type": node["device_type"] if isinstance(node.get("device_type"), str) else UNKNOWN_DEVICE_TYPE,
        "folder": node["folder"] if isinstance(node.get("folder"), str) else "",
        "alias": node["alias"] if isinstance(node.get("alias"), str) else "",
    }
```

and in `parse_topology_payload`, filter on `isinstance(node.get("id"), str)` rather than
`"id" in node`. Add tests for a non-list `parents`, a non-str `alias`, and a list-valued `id`.

## Warnings

### WR-01: The automation secret is accepted as a command-line argument, exposing it in the process table

**File:** `scripts/probe_checkmk_rest_shapes.py:343`
**Issue:** `--rest-secret` lets the secret be passed on the command line, where it is visible to
any process that can read `/proc/<pid>/cmdline` (`ps aux`) for the probe's lifetime, and is
recorded in shell history. The script already reads `CMK_REST_SECRET` from the environment,
which is the safer channel.
**Fix:** Remove the `--rest-secret` flag entirely and require the env var (the script already
`[FAIL]`s with a clear message when it is unset), or read it from a file path
(`--rest-secret-file`).

### WR-02: The probe exits 0 when cleanup fails, leaving a stray tag group on a live site

**File:** `scripts/probe_checkmk_rest_shapes.py:412-425`
**Issue:** `cleanup_probe_tag_group` returns its HTTP status and `results["P6"]` records
success/failure, but the exit code is `return 1 if connection_failure else 0`. A cleanup DELETE
that returns e.g. 409 or 404 sets `results["P6"] = False`, prints a `[FAIL]`, and still exits 0.
Any wrapper or CI step checking only the exit status concludes the live site was left clean when
`gsd_probe_device_type` is in fact still present — and a lingering tag group whose `tags[0]` is
`other` silently becomes a default-bearing group on that site.
**Fix:** Fold cleanup failure into the exit code:

```python
    return 0 if not connection_failure and results.get("P6", False) else 1
```

### WR-03: `folder=""` is overloaded three ways, making `check_device_enrichment` fail on a healthy default deployment

**File:** `scripts/smoke_test_poller.py:325-331`; `scripts/mqtt_poller.py:483`, `613`
**Issue:** `fetch_host_folders` strips the leading slash from `extensions.folder`, so Checkmk's
**root folder** (`"/"`) maps to `""` — the same value used for "host absent from the mapping"
and "REST fetch never succeeded" (`query_devices:613`). The new smoke check then treats
all-empty as one specific diagnosis:

```python
    if not any(folders):
        print("[FAIL] device_enrichment: every device's 'folder' is empty -- this is the "
              "signature of a missing or wrong CMK_REST_SECRET ...")
        return False
```

`phase2_folders`'s "Set up folders?" confirm defaults to `False`
(`src/checkmk_wizard/wizard.py:741`), and declining puts every host in the root folder. So the
*default* wizard path produces a fully correct, fully credentialed deployment that this check
reports as a credential failure — a false FAIL in the primary verification tool, pointing the
operator at the wrong file. The same ambiguity leaks to the dashboard, which cannot tell
"root folder" from "enrichment broken".
**Fix:** Give root its own non-empty label and stop overloading `""`. E.g. in
`fetch_host_folders`, map `"/"` to a sentinel such as `"(root)"` (or keep `""` but publish an
explicit `folder_source`/`folders_available` flag), then narrow the smoke check to fail only
when the `alias`/`folder` keys are absent or when a *known-foldered* host reports `""`.

### WR-04: A 200-but-empty REST response silently defeats the `last_folders` reuse guard

**File:** `scripts/mqtt_poller.py:1074-1082`
**Issue:** The reuse-on-error guard (T-10-12) only triggers on `RestError`. A REST call that
*succeeds* but yields no usable mapping — an automation user whose contact-group permissions
hide every host, a site mid-restart answering with an empty collection, or a response whose
`value` key is missing — returns `{}` from `fetch_host_folders`, and `last_folders = {}`
unconditionally overwrites the last known good map:

```python
            last_folders = fetch_host_folders(...)   # {} on a 200-with-no-hosts
        except RestError as exc:
            _logger.warning("Reusing last known folder map; ...")
```

Every device's folder blanks, the topology signature changes, and a full spurious topology
republish is emitted — exactly the outcome the comment above the declaration says the design
prevents. Nothing is logged, because nothing raised.
**Fix:** Only adopt a non-empty result, and log when a previously-populated map goes empty:

```python
        try:
            fetched = fetch_host_folders(...)
            if fetched or not last_folders:
                last_folders = fetched
            else:
                _logger.warning(
                    "REST folder lookup returned no hosts while %d were known; reusing last map",
                    len(last_folders),
                )
        except RestError as exc:
            _logger.warning("Reusing last known folder map; REST folder refresh failed: %s", exc)
```

### WR-05: No startup validation of the new REST credentials; only the secret is guarded, not the username

**File:** `scripts/mqtt_poller.py:273-274`, `1041-1049`; `deploy/compose.yaml:176-177`
**Issue:** `cmk_rest_username` and `cmk_rest_secret` both default to `""`. With either empty,
`fetch_host_folders` sends `Authorization: Bearer  ` and Checkmk answers 401, which becomes a
`RestError` warning **once per poll cycle, forever** — a 60-second log-noise loop with every
`folder` permanently empty, and no message distinguishing "credential not configured" from
"credential wrong" from "site down". The compose `:?` guard covers `CMK_REST_SECRET` only;
`CMK_REST_USERNAME` is a plain literal, so a typo there degrades identically but silently.
`run_forever` performs a mandatory startup probe for Livestatus columns but no equivalent
one-shot check for REST.
**Fix:** Log one explicit startup message when credentials are absent, and probe once:

```python
    if not config.cmk_rest_username or not config.cmk_rest_secret:
        _logger.warning(
            "CMK_REST_USERNAME/CMK_REST_SECRET not set; every device's `folder` will be "
            "empty. See deploy/.env.example."
        )
```

### WR-06: Misleading warning when `list_hosts()` fails after the tag group was created successfully

**File:** `src/checkmk_wizard/wizard.py:686-698`
**Issue:** `client.list_hosts()` (the backfill count) is inside the same `try` as
`create_host_tag_group`, and both are reported by one handler:
`"could not provision device_type tag group: {exc}"`. If the POST succeeded and only the
subsequent `list_hosts()` failed, the operator is told provisioning failed when it did not —
and on the next run the GET returns 200 and prints "already present", so the two messages
contradict each other with no explanation.
**Fix:** Separate the concerns — the count is cosmetic, the creation is not:

```python
        await client.create_host_tag_group(...)
        console.print("[green]device_type tag group created.[/green]")
        try:
            hosts = await client.list_hosts()
        except CheckmkAPIError as exc:
            console.print(f"[yellow]tag group created; backfill count unavailable: {exc}[/yellow]")
        else:
            ...
```

### WR-07: `_load_device_types()` is re-read and re-validated from disk once per host inside the Phase 4 loop

**File:** `src/checkmk_wizard/wizard.py:997-1000`
**Issue:** The call sits inside `phase4_classification`'s per-host loop, so the file is read,
JSON-parsed and re-validated for every host the operator promotes. Beyond the redundancy, this
makes the failure *timing* bad: `_load_device_types` raises `ValueError` by design, nothing in
Phase 4 or `run()` catches it, so a file edited or removed mid-run (or already invalid, on a run
where Phase 2 short-circuited on "already present" and never loaded it) aborts the wizard after
the operator has already answered several rounds of prompts, losing all Phase 3/4 work. It also
means two hosts in the same run can legitimately be offered different choice lists.
**Fix:** Load once before the loop, so validation happens at a single early point:

```python
    device_type_choices = _load_device_types()
    for scanned in ...:
        ...
        device_type = await questionary.select(
            f"Device type for {hostname}:",
            choices=[questionary.Choice(dt, value=dt) for dt in device_type_choices],
        ).ask_async()
```

### WR-08: The backfill count raises `AttributeError` (not `CheckmkAPIError`) on a null `extensions`/`attributes`

**File:** `src/checkmk_wizard/wizard.py:690-694`
**Issue:**

```python
            if attribute_key not in h.get("extensions", {}).get("attributes", {})
```

`dict.get(k, default)` returns the *stored* value when the key is present, so a host entry with
`"extensions": null` or `"attributes": null` yields `None.get(...)` /
`attribute_key not in None` → `AttributeError`/`TypeError`. Neither is a `CheckmkAPIError`, so
the surrounding handler does not catch it and the whole wizard run dies inside a cosmetic count.
This is the same defensive gap CR-06 describes, in a different module.
**Fix:**

```python
        defaulted = 0
        for h in hosts:
            extensions = h.get("extensions") or {}
            attributes = extensions.get("attributes") or {} if isinstance(extensions, dict) else {}
            if attribute_key not in attributes:
                defaulted += 1
```

### WR-09: Documentation claims `alias` is empty for hosts without one; Livestatus defaults it to the hostname

**File:** `docs/Podman setup for checkmk, minio, mosquitto, worker.md:276`;
`scripts/smoke_test_poller.py:339-341`
**Issue:** The docs state *"`alias` is Checkmk's native host alias ... it is empty for any host
without one."* The Phase 10 live verification recorded in `scripts/mqtt_poller.py:113-116`
confirms only the *set* case (`core-router-1` distinguishable from the hostname); the *unset*
case was not observed. Checkmk's core config conventionally materialises `alias` as the host
name when the WATO attribute is unset, in which case the Livestatus `alias` column is never
empty, `DeviceSnapshot.alias = ""` is unreachable in practice, and the smoke check's
`if not aliases: print("[INFO] ... no device carries a non-empty alias")` branch is dead code.
Phase 11's planned "prefer alias over hostname" logic would then be a silent no-op for
un-aliased hosts rather than the documented fallback.

This is the one assumption in the phase that is documented as fact without a live observation
behind it, in a codebase whose stated convention is that Checkmk's live behaviour is the source
of truth.
**Fix:** Verify with one LQL query against a host that has never had an alias set —
`GET hosts\nColumns: name alias\nFilter: name = <host>\nOutputFormat: json\n\n` — then either
correct the docs sentence and drop the dead smoke-check branch, or normalise
`alias == name` to `""` in `query_devices` so the published contract matches the documented one.

### WR-10: `"wato" in f` substring test false-FAILs any legitimate folder whose name contains "wato"

**File:** `scripts/smoke_test_poller.py:333-340`
**Issue:**

```python
    bad_folders = [f for f in folders if f and ("wato" in f or f.startswith("/omd"))]
```

The check exists to detect the WR-07 filesystem-path regression, but an unanchored substring
match on a *semantic* folder label fires on any operator-chosen folder name containing the
letters `wato` — and the WR-07 finding it guards against was itself triggered by a site named
`wato`, so a `wato`-named grouping on this stack is not hypothetical. Since folder values now
arrive leading-slash-stripped, `f.startswith("/omd")` can never match either, making the second
half of the condition dead.
**Fix:** Detect the actual regression shape rather than a substring:

```python
    # A REST folder association is a slash-separated label path with no
    # leading slash and no OMD path segments; the old derive_folder() bug
    # produced values containing a literal 'wato' path *segment*.
    bad_folders = [f for f in folders if f and ("wato" in f.split("/") or "omd" in f.split("/"))]
```

### WR-11: `_load_device_types` is duplicated in the probe script without its load-bearing validation

**File:** `scripts/probe_checkmk_rest_shapes.py:106-107` vs.
`src/checkmk_wizard/wizard.py:633-660`
**Issue:** The probe has its own `_load_device_types()` that is a bare
`json.loads(path.read_text())` with none of the wizard's validation. The wizard's docstring
explains at length *why* that validation is load-bearing: Checkmk silently assigns `tags[0]` as
the default for every host with no explicit value (PITFALLS.md Pitfall 8). The probe feeds the
same list straight into a real `POST .../host_tag_group/collections/all` against a **live site**
(line 173-182), so a `device_types.json` whose first entry is not `other` gets a real device type
installed as a site-wide default — mitigated only by the throwaway group id and a cleanup that
can itself fail silently (WR-02). The two copies can also drift as the file's schema evolves.
**Fix:** Since D-01 forbids importing from `checkmk_wizard`, either inline the same three
validations in the probe (non-empty list of str, `raw[0] == "other"`) or have the probe not read
the file at all and use a hardcoded two-element `["other", "probe"]` list — it only needs *a*
valid body shape, not the real taxonomy.

## Info

### IN-01: `_device_type_and_alias_attributes` deviates from the module's type-annotation and naming conventions

**File:** `src/checkmk_wizard/wizard.py:662-675`
**Issue:** The signature is `def _device_type_and_alias_attributes(h: OnboardedHost) -> dict:`
with a bare `dict` return annotation and a single-letter parameter. The derived convention in
this module and in `api.py` is the parameterised form — `attributes: dict[str, Any] | None`
(`api.py:126`), `attributes: dict[str, Any]` (`api.py:215`) — and descriptive parameter names;
`h` appears elsewhere only as a comprehension variable, never as a function parameter.
**Fix:** Recommend `def _device_type_and_alias_attributes(host: OnboardedHost) -> dict[str, Any]:`
and rename the body's `h.` references accordingly. Advisory only — does not block.

### IN-02: `missing_keys` holds device ids, not key names

**File:** `scripts/smoke_test_poller.py:318`
**Issue:** `missing_keys = [d.get("id", "?") for d in devices if "alias" not in d or "folder" not in d]`
collects *device ids*, which the print statement then renders as
`device(s) {missing_keys} missing 'alias' and/or 'folder'`. The name contradicts the contents and
misleads anyone extending the check. The derived convention in this file is that identifier lists
are named for what they hold (`devices`, `folders`, `aliases`, `bad_folders` a few lines below).
**Fix:** Recommend renaming to `devices_missing_enrichment`. Advisory only — does not block.

### IN-03: `cmk_rest_base_url` interpolates an unvalidated `cmk_site_id` into the REST URL path

**File:** `scripts/mqtt_poller.py:424-429`
**Issue:** `f"http://{config.cmk_rest_host}:{config.cmk_rest_port}/{config.cmk_site_id}/check_mk/api/1.0"`
inserts a raw env var into a URL path with no validation or quoting; a `CMK_SITE_ID` containing
`../` or a `/` would silently retarget the request path. The derived convention in this repo is
that site names are validated against `_SITE_NAME_RE` before use
(`src/checkmk_wizard/wizard.py:63`). Severity is low: the value is operator-supplied via compose
rather than attacker-controlled, and the worst realistic outcome is a confusing 404.
**Fix:** Recommend `urllib.parse.quote(config.cmk_site_id, safe="")`, or a
`re.fullmatch(r"[a-z0-9_]{1,16}", ...)` check in `from_env()` that falls back to the default with
a warning (matching `_env_int`'s bad-value behaviour). Advisory only — does not block.

---

_Reviewed: 2026-09-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
