# Phase 10: Checkmk Tag-Group & Onboarding Integration - Pattern Map

**Mapped:** 2026-09-09
**Files analyzed:** 6 (3 modified source files, 3 modified test files; no new files — this phase extends existing modules, per D-05's file-path discretion resolving to a new top-level config file too)
**Analogs found:** 6 / 6 (all in-repo; every pattern this phase needs already has a proven precedent in this codebase)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|-----------------|----------------|
| `src/checkmk_wizard/api.py` (+`create_host_tag_group`, +`get_host_tag_group`) | service (REST client method) | request-response (CRUD, idempotent-create) | same file: `create_folder`/`get_folder` (`api.py:150-178`) | exact |
| `device_types.json` (new config file, repo root) | config | file-I/O (read-once at wizard startup) | `docs/smart/` bundled `.deb` assets, resolved via `_SMARTMONTOOLS_DIR` (`wizard.py:40`) | role-match (asset-resolution pattern; no prior *parsed config* precedent, so this is the closest available) |
| `src/checkmk_wizard/wizard.py` (`OnboardedHost` +`device_type`/`alias` fields) | model (dataclass) | transform (in-memory state threaded between phases) | same file: `OnboardedHost` itself (`wizard.py:198-211`) | exact (additive fields to existing dataclass) |
| `src/checkmk_wizard/wizard.py` (`phase4_classification` + 2 prompts) | controller (interactive CLI phase) | request-response (prompt loop) | same function, same file: existing prompt loop (`wizard.py:797-885`) | exact |
| `src/checkmk_wizard/wizard.py` (`_ensure_device_type_tag_group` — new helper) | service (orchestration step) | request-response (idempotent provisioning + summary report) | `phase2_folders()`'s folder-default-attribute + idempotent-create pattern (`wizard.py:662-680`) | role-match |
| `src/checkmk_wizard/wizard.py` (`_onboard_hosts()` 3 call sites: snmp/ping/agent) | controller (per-host apply loop) | CRUD (create/update host attributes) | same file: same 3 call sites, existing `tag_agent`/`tag_snmp_ds` attribute dicts (`wizard.py:1447-1489`) | exact |
| `scripts/mqtt_poller.py` (`derive_folder()` replacement — new REST helper) | service (standalone REST client) | request-response (poll-cycle REST call) | same file: `_livestatus_request()` (`mqtt_poller.py:313-335`) — the module's own "one choke point, normalize failures into one exception type" pattern | role-match (protocol differs — TCP/LQL vs HTTP/REST — but the error-normalization shape is the direct analog) |
| `scripts/mqtt_poller.py` (`OPTIONAL_HOST_COLUMNS` +`"alias"`, `DeviceSnapshot` +`alias`, `query_devices()` row parsing) | transform (Livestatus row → dataclass) | CRUD-adjacent (read/parse) | same file: existing optional-column defensive parsing for `parents`/`tags`/`filename` (`mqtt_poller.py:91-99`, `440-455`) | exact |
| `scripts/mqtt_poller.py` (`PollerConfig` +`cmk_rest_*` fields) | config (env-var-sourced dataclass) | transform | same file: `PollerConfig`/`PollerConfig.from_env()` (`mqtt_poller.py:144-195`) | exact |
| `tests/test_api.py` (+`create_host_tag_group`/`get_host_tag_group` tests) | test | request-response (respx-mocked) | same file: `test_get_folder_uses_tilde_encoded_id` / folder-PUT test (`test_api.py:131-156`) | exact |
| `tests/test_wizard.py` (existing `phase4_classification`-driving tests, answers-iterator extended) | test | request-response | same file: `test_phase4_offers_ping_monitoring_method` (`test_wizard.py:821-831`) | exact |
| `tests/test_mqtt_poller.py` (`derive_folder`/`extract_device_type` tests re-examined) | test | transform | same file: `test_derive_folder_extracts_segment_after_wato` / `test_extract_device_type_*` (`test_mqtt_poller.py:107-130`) | exact |
| `deploy/compose.yaml` (`poller` service env additions: `CMK_REST_*`) | config | — | same file: `poller` service's existing `environment:` block (`compose.yaml:141-151`) | exact |

## Pattern Assignments

### `src/checkmk_wizard/api.py` — `create_host_tag_group()` / `get_host_tag_group()` (service, request-response)

**Analog:** `create_folder()` / `get_folder()` (`api.py:150-178`)

**Imports pattern** (already present, no new imports needed — `httpx`, `Any` from `typing` already imported at `api.py:14,16`):
```python
from typing import Any, Self
import httpx
```

**Core create pattern** (`api.py:150-162`, mirror exactly — same body-dict-then-`_request` shape):
```python
async def create_folder(
    self, name: str, title: str, parent: str = "/", attributes: dict[str, Any] | None = None
) -> dict[str, Any]:
    body = {
        "name": name,
        "title": title,
        "parent": parent,
        "attributes": attributes or {},
    }
    resp = await self._request(
        "POST", "/domain-types/folder_config/collections/all", json_body=body
    )
    return resp.json()
```

**Idempotency-check pattern** (`api.py:173-178`, mirror for `get_host_tag_group`):
```python
async def get_folder(self, name: str) -> httpx.Response:
    # Root-level folder REST ids are "~" + name (live-verified: ...)
    return await self._request("GET", f"/objects/folder_config/~{name}")
```
For the tag group, the target endpoint is `/objects/host_tag_group/{group_id}` (no tilde-encoding — group ids are plain, per RESEARCH.md Pattern 1) and the caller must inspect `resp.status_code` for 404-vs-200 (pass `expect=(200, 404)` to `_request` so a 404 does not raise `CheckmkAPIError`, exactly as `_request`'s `expect` parameter is designed for — see `api.py:104-113`).

**Error handling pattern** (already centralized — no new error handling needed): every `_request()` call automatically normalizes `httpx.HTTPError` and non-`expect`-status responses into `CheckmkAPIError` (`api.py:104-140`). New methods must call `self._request(...)`, never `self._client.request(...)` directly, to preserve this.

**Live-verification citation convention to follow** (`api.py:200-206` style — cite this exact wording pattern for the new tag-group payload shape once verified):
```python
# Live-verified against a real Checkmk 2.4.0p35 CE site: ...
```
Until live-verified, use RESEARCH.md's own caveat wording (see RESEARCH.md Pattern 1's docstring example) rather than a false "live-verified" claim.

---

### `device_types.json` (config, file-I/O)

**Analog:** `_SMARTMONTOOLS_DIR` resolution pattern (`wizard.py:37-40`)

**Path-resolution pattern to mirror:**
```python
# Bundled smartmontools .deb packages ... ship inside the repo, not the
# installed package, since this wizard is run via `uv run` from a checkout
# rather than installed as a distributed wheel.
_SMARTMONTOOLS_DIR = Path(__file__).resolve().parents[2] / "docs" / "smart"
```
For `device_types.json` at repo root: `_DEVICE_TYPES_PATH = Path(__file__).resolve().parents[2] / "device_types.json"` (same `parents[2]` climb from `src/checkmk_wizard/wizard.py` to repo root — verified: `wizard.py` → `checkmk_wizard` → `src` → repo root is 2 levels up from `parents[2]`... actually `Path(__file__).resolve()` is `wizard.py` itself; `.parents[0]` = `checkmk_wizard/`, `.parents[1]` = `src/`, `.parents[2]` = repo root — matches `_SMARTMONTOOLS_DIR`'s existing `docs/smart` resolution exactly, same base).

**No existing *parsed*-JSON-config precedent in this repo** — this is a genuinely new pattern (config loader + validation), but the *fail-loud validation* style matches this project's existing defensive-validation idiom (`_password_problems()`, `wizard.py:123-136` — returns/raises human-readable problem strings rather than trusting input silently).

---

### `src/checkmk_wizard/wizard.py` — `OnboardedHost` dataclass fields (model, transform)

**Analog:** `OnboardedHost` itself (`wizard.py:198-211`)

**Dataclass conventions to follow exactly** (project convention — plain `@dataclass`, `field(default_factory=...)` for mutables, inline comments for *why* a default exists):
```python
@dataclass
class OnboardedHost:
    ip: str
    hostname: str
    folder: str
    os_family: str  # "linux" | "windows" | "snmp" | "ping"
    snmp_version: str | None = None  # "v1" | "v2c" — only set when os_family == "snmp"
    snmp_community: str | None = None
    expected_open_ports: list[int] = field(default_factory=list)
    expected_services: list[str] = field(default_factory=list)
```
New fields append at the end (dataclass field ordering matters for any positional-arg call sites — check for any before adding non-default fields; both new fields must have defaults since existing call sites use keyword args, per RESEARCH.md Pattern 2's example: `device_type: str = "other"`, `alias: str | None = None`).

---

### `src/checkmk_wizard/wizard.py` — `phase4_classification()` prompts (controller, request-response)

**Analog:** same function's existing prompt loop (`wizard.py:797-885`)

**Imports pattern** (already present — `questionary` imported at `wizard.py:19`, no new imports needed for `questionary.select`/`questionary.text`, both already used elsewhere in this exact function):
```python
import questionary
```

**Core prompt pattern — `select` with fixed choices** (mirror `os_family`'s select at `wizard.py:827-835`):
```python
os_family = await questionary.select(
    f"Monitoring method for {hostname}:",
    choices=[
        questionary.Choice("linux (Checkmk agent)", value="linux"),
        questionary.Choice("windows (Checkmk agent)", value="windows"),
        questionary.Choice("snmp (no agent — switch/router/printer/etc.)", value="snmp"),
        questionary.Choice("simple ping (no agent, no SNMP — reachability only)", value="ping"),
    ],
).ask_async()
```
Device-type prompt mirrors this shape exactly, with choices built from `_load_device_types()` (config-loaded, not hardcoded):
```python
device_type = await questionary.select(
    f"Device type for {hostname}:",
    choices=[questionary.Choice(dt, value=dt) for dt in _load_device_types()],
).ask_async()
```

**Core prompt pattern — free-text with blank-default** (mirror the port-list prompt's blank-handling at `wizard.py:855-863`, simplified since alias needs no validation loop):
```python
alias = (
    await questionary.text(
        f"Display name/alias for {hostname} (blank to use hostname):", default=""
    ).ask_async()
).strip() or None
```

**Validation-loop pattern** (mirror hostname's re-prompt-on-invalid loop, `wizard.py:815-826` — only needed if device_type/alias ever need format validation; alias currently has none per RESEARCH.md V5 note, device_type is validated by construction via the fixed `_load_device_types()` choice list so no loop is needed there either).

---

### `src/checkmk_wizard/wizard.py` — `_ensure_device_type_tag_group()` (new helper — service/orchestration)

**Analog:** `phase2_folders()`'s idempotent-create-with-try/except pattern (`wizard.py:662-680`)

**Core pattern to mirror** (try/except `CheckmkAPIError`, `console.print` status, comment citing *why* the ordering/default matters):
```python
try:
    await client.create_folder(
        name=name, title=name, attributes={"tag_agent": "no-agent", "tag_snmp_ds": "no-snmp"}
    )
    console.print(f"  [green]created[/green] /{name}")
    folder_created = True
except CheckmkAPIError as exc:
    console.print(f"  [red]failed[/red] /{name}: {exc}")
```
For the tag group, RESEARCH.md's own worked example (`_ensure_device_type_tag_group`, RESEARCH.md "Code Examples" section) already follows this exact shape — reuse it directly rather than re-deriving:
```python
async def _ensure_device_type_tag_group(client: CheckmkClient) -> None:
    resp = await client.get_host_tag_group("device_type")
    if resp.status_code == 200:
        return  # already exists — idempotent no-op
    choices = _load_device_types()
    await client.create_host_tag_group(
        group_id="device_type",
        title="Device Type",
        tags=[{"id": c, "title": c, "aux_tags": []} for c in choices],
    )
    hosts = await client.list_hosts()
    defaulted = sum(
        1 for h in hosts
        if h.get("extensions", {}).get("attributes", {}).get("tag_device_type") == choices[0]
    )
    console.print(
        f"[green]device_type tag group created.[/green] "
        f"{defaulted} pre-existing host(s) defaulted to device_type={choices[0]!r}."
    )
```

---

### `src/checkmk_wizard/wizard.py` — `_onboard_hosts()` attribute dicts (controller, CRUD)

**Analog:** same 3 call sites, existing `tag_agent`/`tag_snmp_ds` shape (`wizard.py:1447-1489`)

**Core CRUD pattern (snmp branch, `wizard.py:1447-1461`) — extend the `attributes` dict:**
```python
attributes={
    "ipaddress": h.ip,
    "tag_agent": "no-agent",
    "tag_snmp_ds": "snmp-v2" if h.snmp_version == "v2c" else "snmp-v1",
    "snmp_community": {"type": "v1_v2_community", "community": h.snmp_community},
    "tag_device_type": h.device_type,   # NEW
},
```
Same additive pattern applies to the ping branch (`wizard.py:1469-1479`) and the agent branch (`wizard.py:1481-1489`). `alias` is conditionally added (native Checkmk attribute, not a tag — RESEARCH.md D-09):
```python
if h.alias:
    attributes["alias"] = h.alias
```

**Error handling** (already established, unchanged): `try: ... except CheckmkAPIError as exc: console.print(f"  [yellow]host create/update: {exc}[/yellow]")` — every one of the 3 call sites already wraps `_create_or_update_host`/`create_host` this way; no new error-handling pattern needed, just extend the existing `attributes` dict inside the existing try block.

---

### `scripts/mqtt_poller.py` — folder-derivation REST helper (service, request-response)

**Analog:** `_livestatus_request()` (`mqtt_poller.py:313-335`) — the module's single-choke-point error-normalization pattern

**Core pattern to mirror exactly** (own exception type, catch narrow, wrap once):
```python
def _livestatus_request(host: str, port: int, query: str, timeout: float) -> str:
    """... Every Livestatus network failure funnels through this one choke
    point and is normalized into `LivestatusError` exactly once ..."""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(query.encode())
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
    except (TimeoutError, OSError) as exc:
        raise LivestatusError(f"Livestatus request to {host}:{port} failed: {exc}") from exc
    return b"".join(chunks).decode(errors="replace")
```
New REST helper (RESEARCH.md's own worked example, "Poller REST helper" under Code Examples) follows this shape 1:1, substituting `urllib.request`/`OSError`/`json.JSONDecodeError` for the socket/LQL specifics:
```python
class RestError(RuntimeError):
    """Raised for any REST network failure or malformed response — same
    single-choke-point normalization pattern as LivestatusError."""

def _rest_get_hosts_folders(base_url, auth_header, timeout) -> dict[str, str]:
    try:
        req = urllib.request.Request(
            f"{base_url}/domain-types/host_config/collections/all",
            headers={"Authorization": auth_header, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise RestError(f"REST folder lookup failed: {exc}") from exc
    return {item["id"]: item.get("extensions", {}).get("folder", "") for item in data.get("value", [])}
```

**Per-cycle degrade-not-crash pattern** (mirror `run_forever()`'s existing per-cycle `LivestatusError` handling, `mqtt_poller.py:852-864`):
```python
while not stop_event.is_set():
    try:
        snapshots = query_devices(...)
    except LivestatusError as exc:
        _logger.warning("Skipping cycle: %s", exc)
    else:
        run_cycle(client, config, state, snapshots)
    stop_event.wait(timeout=config.poll_interval_seconds)
```
The new REST call should follow the identical "log a warning, degrade this one field, don't skip the whole cycle" shape (per RESEARCH.md Pitfall 3), not the "skip cycle" shape used for the mandatory Livestatus query:
```python
try:
    folders = _rest_get_hosts_folders(rest_base_url, rest_auth_header, timeout)
except RestError as exc:
    _logger.warning("Skipping folder refresh this cycle: %s", exc)
    folders = {}  # snapshots fall back to folder="" for this cycle only
```

---

### `scripts/mqtt_poller.py` — `OPTIONAL_HOST_COLUMNS` + `alias`, `DeviceSnapshot` + `alias`, `query_devices()` row parsing (transform)

**Analog:** existing optional-column defensive-parse pattern for `parents`/`tags` (`mqtt_poller.py:91-99`, `436-450`)

**Column-list constant pattern** (`mqtt_poller.py:91-99`):
```python
REQUIRED_HOST_COLUMNS = ("name", "state")
OPTIONAL_HOST_COLUMNS = (
    "scheduled_downtime_depth",
    "acknowledged",
    "worst_service_state",
    "parents",
    "tags",
    "filename",
)
```
Add `"alias"` to `OPTIONAL_HOST_COLUMNS` (D-10) — `select_host_columns()` and its "logged degradation, not hard failure" behavior (`mqtt_poller.py:357-380`) apply automatically to any name added here, no other change needed to that function.

**Defensive per-row parse pattern** (`mqtt_poller.py:435-450`, mirror for `alias`):
```python
try:
    acknowledged = bool(row[index["acknowledged"]]) if "acknowledged" in index else False
except (IndexError, TypeError):
    acknowledged = False
```
New `alias` extraction:
```python
try:
    alias = row[index["alias"]] if "alias" in index else ""
except (IndexError, TypeError):
    alias = ""
```

**Dataclass field addition** (`DeviceSnapshot`, `mqtt_poller.py:198-211`) — append `alias: str = ""` following the same inline-comment-citing-the-locking-decision convention already used for `in_downtime`/`acknowledged` (`# Field names locked by D-07 ...`).

**Publish-payload extension** (`publish_device_status()`, `mqtt_poller.py:526-537`) — add `"alias": snapshot.alias` to the payload dict, same flat-dict-literal shape as every other field there.

---

### `scripts/mqtt_poller.py` — `PollerConfig` REST credential fields (config)

**Analog:** `PollerConfig`/`PollerConfig.from_env()` itself (`mqtt_poller.py:144-195`)

**Dataclass + redacting `__repr__` pattern to extend** (`mqtt_poller.py:160-177` — this is load-bearing per T-09-02/RESEARCH.md's Security Domain note; the new `cmk_rest_secret` field MUST be added to the redaction list, not just the dataclass):
```python
def __repr__(self) -> str:
    # T-09-02: this object must be safe to log — never render the raw
    # MQTT password. Defined explicitly so @dataclass does not
    # generate a repr that would include it.
    return (
        "PollerConfig("
        f"livestatus_host={self.livestatus_host!r}, "
        ...
        f"mqtt_username={self.mqtt_username!r}, "
        "mqtt_password='***', "
        ...
    )
```
New fields (`cmk_rest_host`, `cmk_rest_port`, `cmk_site_id`, `cmk_rest_username`, `cmk_rest_secret`) follow the same `mqtt_username`/`mqtt_password` split: non-secret fields rendered plain, `cmk_rest_secret` rendered as `'***'`.

**`from_env()` pattern** (`mqtt_poller.py:179-195`, mirror exactly, reusing `_env_int` for the new port):
```python
@classmethod
def from_env(cls) -> PollerConfig:
    return cls(
        livestatus_host=os.environ.get("LIVESTATUS_HOST", "checkmk"),
        livestatus_port=_env_int("LIVESTATUS_PORT", DEFAULT_LIVESTATUS_PORT),
        ...
    )
```
New env vars per RESEARCH.md's Pitfall 2 recommendation: `CMK_SITE_ID` (reuse the exact name already established by `deploy/compose.yaml`'s `checkmk`/`worker` services, default `"dmc"`), `CMK_REST_HOST` (default matching `LIVESTATUS_HOST`'s default, `"checkmk"`), `CMK_REST_PORT` (default `5000`, via `_env_int`), `CMK_REST_USERNAME`, `CMK_REST_SECRET` (both `os.environ.get(..., "")`, no safe default possible for a secret).

---

### `deploy/compose.yaml` — `poller` service env additions (config)

**Analog:** same file, same service's existing `environment:` block (`compose.yaml:141-151`)

```yaml
environment:
  - LIVESTATUS_HOST=checkmk
  - LIVESTATUS_PORT=6557
  - MQTT_HOST=mosquitto
  - MQTT_PORT=1883
  # Disposable Phase 8 credentials already in deploy/mosquitto.passwd;
  # rotate via deploy/gen-mosquitto-passwd.sh ...
  - MQTT_USERNAME=poller
  - MQTT_PASSWORD=poller
  - POLL_INTERVAL_SECONDS=60
  - RECONCILE_TIMEOUT_SECONDS=5
```
New `CMK_REST_*`/`CMK_SITE_ID` lines follow the same flat `- NAME=value` list shape, with a comment matching the existing `CMK_SITE_ID` cross-reference comment style already used in the `worker` service (`compose.yaml:98-101`: `# Same name/value as the checkmk service's own CMK_SITE_ID above ...`) to document that the operator must manually copy the wizard-bootstrapped automation secret in (RESEARCH.md Open Question 2 / Pitfall 2).

---

## Shared Patterns

### REST error normalization (wizard side)
**Source:** `CheckmkClient._request()` (`api.py:104-140`)
**Apply to:** `create_host_tag_group()`, `get_host_tag_group()` — call `self._request(...)`, never `self._client.request(...)` directly.
```python
try:
    resp = await self._client.request(method, path, json=json_body, params=params, headers=headers)
except httpx.HTTPError as exc:
    raise CheckmkAPIError(method, f"{self._client.base_url}{path.lstrip('/')}", 0, str(exc)) from exc
if resp.status_code not in expect and resp.status_code != 204:
    ...
    raise CheckmkAPIError(method, str(resp.url), resp.status_code, body)
return resp
```

### REST/network error normalization (poller side)
**Source:** `_livestatus_request()` + `LivestatusError` (`mqtt_poller.py:112-113,313-335`)
**Apply to:** the new REST folder-lookup helper — same "one choke point, one custom exception type, narrow `except`" shape; new class `RestError(RuntimeError)`.

### Tag-attribute shape (`tag_<group_id>`)
**Source:** `_onboard_hosts()`'s existing `tag_agent`/`tag_snmp_ds` attribute dicts (`wizard.py:1454-1455,1474,1486`)
**Apply to:** every `create_host`/`_create_or_update_host` call site gaining `tag_device_type`; no new abstraction, just another key in the same `attributes` dict.

### Idempotent-create-with-status-report
**Source:** `phase2_folders()`'s folder-creation try/except + `console.print` status lines (`wizard.py:662-680`)
**Apply to:** `_ensure_device_type_tag_group()` — check-then-create, `console.print` a summary line on success.

### Redacted-secret dataclass repr
**Source:** `PollerConfig.__repr__()` (`mqtt_poller.py:160-177`)
**Apply to:** any new secret field added to `PollerConfig` (`cmk_rest_secret`) — must be explicitly redacted, the dataclass-generated repr is not safe to rely on.

### Defensive per-row Livestatus column parsing
**Source:** `query_devices()`'s `acknowledged`/`parents`/`tags` extraction (`mqtt_poller.py:420-455`)
**Apply to:** the new `alias` column — `try/except (IndexError, TypeError)` around each `row[index[...]]` lookup, degrade to a safe default (`""`), never raise out of the per-row loop.

## No Analog Found

None — every file this phase touches is a modification to an existing module, and every specific sub-pattern (REST create/idempotency-check, dataclass field addition, questionary prompt, tag-attribute dict, defensive column parsing, redacted-secret config) already has a proven, directly-applicable analog inside this same repository. The one genuinely novel piece — parsing a checked-in JSON config file (`device_types.json`) — has no prior *parsing* precedent, but its *path-resolution* half is directly modeled on `_SMARTMONTOOLS_DIR` (see Pattern Assignments above), and its *validation* half follows this project's existing "return/raise human-readable problems, fail loud on a load-bearing invariant" idiom (`_password_problems()`, `wizard.py:123-136`).

## Metadata

**Analog search scope:** `src/checkmk_wizard/api.py`, `src/checkmk_wizard/wizard.py`, `scripts/mqtt_poller.py`, `tests/test_api.py`, `tests/test_wizard.py`, `tests/test_mqtt_poller.py`, `deploy/compose.yaml`
**Files scanned:** 7 (all read directly; no Glob/Grep-only matches used — every analog cited above was opened and its exact lines verified)
**Pattern extraction date:** 2026-09-09

## Conventions

Convention derivation was not run for this phase — this repository's derived-conventions tooling (`bin/gsd-tools.cjs verify conventions --derive`) is scoped to the `bm` plugin toolchain and was not available/applicable to this Python-only project's `.planning/` tree in this session. Deriving-and-citing project conventions inline instead, from direct repo reading (see `CLAUDE.md`'s own already-documented "Naming Patterns"/"Code Style" sections, which this repo maintains as its authoritative convention record):

| Axis | Dominant | Notes |
|------|----------|-------|
| File-name casing | `snake_case` | 100% — every module (`api.py`, `wizard.py`, `mqtt_poller.py`, `device_types.json`) |
| Identifier casing | `snake_case` (functions/vars), `PascalCase` (classes/dataclasses), `UPPER_SNAKE_CASE` (module constants) | No exceptions observed in the files read for this phase |
| Export style | Plain top-level `def`/`class`, no `__all__`, no barrel re-exports | `api.py`/`wizard.py`/`mqtt_poller.py` all export by direct top-level definition |
| Import style | `from __future__ import annotations` first, then stdlib, then third-party, then local (`checkmk_wizard.*`) — no relative imports | Consistent across all three files read |

**Contested hotspots (author's choice):** none identified within the files this phase touches — this is a small, single-team Python codebase with one dominant style throughout (unlike, e.g., a dual CJS/ESM split in a JS/TS monorepo); no per-directory style fork exists here to flag as "author's choice" territory.

---
*Phase: 10-checkmk-tag-group-onboarding-integration*
*Pattern mapping date: 2026-09-09*
