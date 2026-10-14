# Phase 17: Cloud MQTT Contract and S3 Archive Feed - Pattern Map

**Mapped:** 2026-10-14
**Files analyzed:** 14 (5 new, 9 modified)
**Analogs found:** 13 / 14

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `deploy/render-mosquitto-bridge.sh` (new) | config renderer | transform | `deploy/render-mosquitto-acl.sh` | exact |
| `deploy/mosquitto.bridge.template` (new) | config | event-driven | `deploy/mosquitto.acl.template` | role-match |
| `deploy/mosquitto.conf` (mod: include_dir, queue limits) | config | event-driven | itself | exact |
| `deploy/mosquitto.acl.template` (mod: `user bridge`) | config | request-response | itself, `user analytics` block | exact |
| `deploy/mosquitto.cloud-acl.example` (new) | config | request-response | `deploy/mosquitto.acl.template` | role-match |
| `deploy/compose.yaml` (mod: mosquitto entrypoint, env) | config | batch | mosquitto service lines 100-135 | exact |
| `deploy/init-env.sh` (mod: SITE_SEN) | config/script | request-response | CMK_SITE_ID block, lines 68-92 | exact |
| `scripts/mqtt_poller.py` (mod: v5, `_publish_json` event_id, throttle, history publish, `SITE_SEN`) | service | pub-sub | itself (lines 645-680, 2791-2880, 2422) | exact |
| `analytics/topics.py` (mod: configurable prefix) | utility | transform | itself, mirrored in poller `site_topic` | exact |
| `analytics/service.py` + `analytics/config.py` (mod: v5, persistent session, history subscriber and dedupe) | service | event-driven | `build_client` lines 197-216, `AnalyticsConfig.from_env` | exact |
| `src/checkmk_wizard/wizard.py` (mod: SITE_SEN prompt and `.env` write) | controller | request-response | `phase1_site_bringup` site-name prompt (~500-530) and `CMK_PUBLIC_HOST` block (~3050-3075) | role-match |
| `tests/test_mosquitto_bridge_render.py` (new) | test | transform | `tests/test_mosquitto_acl.py` | exact |
| `tests/test_mqtt_poller.py`, `test_analytics_*`, `test_mosquitto_acl.py`, `test_wizard.py` (mod) | test | n/a | themselves | exact |
| dashboard staleness fix (`dashboard-react/src/lib/staleness.ts`) and `config.json` SEN | utility | transform | not read | no analog read (see below) |

## Pattern Assignments

### `deploy/render-mosquitto-bridge.sh` (config renderer, transform)

**Analog:** `deploy/render-mosquitto-acl.sh` (whole file, 45 lines). Copy structure: `set -eu`, arg count check, validate BEFORE sed, `umask 077`, write to `$output.tmp.$$`, grep for leftover `@...@` placeholders, `mv`.

**Validation pattern** (lines 15-40):
```sh
set -eu
if [ "$#" -ne 2 ]; then
  echo "usage: $0 TEMPLATE OUTPUT" >&2
  exit 2
fi
template=$1
output=$2
site=${CMK_SITE_ID-}
case $site in
  *[!A-Za-z0-9_]*)
    echo "render-mosquitto-acl: CMK_SITE_ID contains characters outside [A-Za-z0-9_]" >&2
    exit 1
    ;;
esac
if ! printf '%s\n' "$site" | grep -Eqx '[A-Za-z][A-Za-z0-9_]{0,15}'; then
  ...
fi
```
**Render pattern** (lines 42-52):
```sh
umask 077
tmp="$output.tmp.$$"
sed "s/@SITE_ID@/$site/g" "$template" > "$tmp"
if grep -q '@SITE_ID@' "$tmp"; then
  rm -f "$tmp"; echo "...placeholder remained after rendering" >&2; exit 1
fi
mv "$tmp" "$output"
```
Extend: also validate `SITE_SEN` with `grep -Eqx '[1-9][0-9]{0,17}'`; validate CLOUD host charset before sed; the password goes through sed, so reject `/`, `&`, `|`, newline (or use a different sed delimiter plus charset check). Exit 0 without writing when the cloud feed is not configured (bridge is optional).

### `deploy/mosquitto.bridge.template` (config)

**Analog:** `deploy/mosquitto.acl.template` header comment style (no env expansion, rendered at start). Body is the RESEARCH Pattern 1 block verbatim (`connection cloud-@SITE_SEN@-@SITE_ID@`, `bridge_protocol_version mqttv50`, `cleansession false`, `remote_clientid`, `notifications false`, `topic # out 1 sites/@SITE_ID@/ app/@SITE_SEN@/@SITE_ID@/`). Note `bridge_session_expiry_interval` and the global-only `max_queued_messages`/`max_queued_bytes` belong in `mosquitto.conf`, declared before any `listener` line.

### `deploy/mosquitto.acl.template` (add bridge user)

**Analog:** the existing `user analytics` / `user wsreader` blocks.
```
user wsreader
topic read sites/@SITE_ID@/lan/#
```
Add `user bridge` with `topic read sites/@SITE_ID@/#` only. Also the history topic `sites/@SITE_ID@/history/<table>`: poller already has `readwrite sites/@SITE_ID@/#` so it can publish; `wsreader` reads `lan/#` only so history stays hidden from the browser. Add a `user analytics` read for `sites/@SITE_ID@/history/#` only if local analytics consumes it.

### `deploy/compose.yaml` mosquitto service (entrypoint, volumes)

**Analog:** same service, lines 100-135. Pattern to follow:
```yaml
        mosquitto_passwd -b /mosquitto/config/mosquitto.passwd analytics "$$MQTT_ANALYTICS_PASSWORD";
        ...
        sh /mosquitto/render-acl.sh /mosquitto/acl.template /mosquitto/config/mosquitto.acl;
        chown mosquitto:mosquitto /mosquitto/config/mosquitto.acl;
        chmod 0700 /mosquitto/config/mosquitto.acl;
        exec /docker-entrypoint.sh /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
...
      - ./render-mosquitto-acl.sh:/mosquitto/render-acl.sh:ro,z
```
Add: `mosquitto_passwd ... bridge "$$MQTT_BRIDGE_PASSWORD"`, a render-bridge step with identical chown/chmod 0700, bind mounts for the new script, template and cloud CA, and `SITE_SEN`/`CLOUD_*` env. The `${VAR:?}` convention is used for passwords with no safe default. `tests/test_mosquitto_acl.py::test_compose_wires_the_renderer` asserts exact strings from this block, so keep the existing lines unchanged and only add.

### `deploy/init-env.sh` (SITE_SEN)

**Analog:** CMK_SITE_ID block lines 68-92 (`get_val`, `set_val`, `summary+=`, prompt loop with regex).
```bash
site="$(get_val CMK_SITE_ID)"
if [ -n "$site" ]; then
    summary+=("CMK_SITE_ID: kept ($site)")
else
    while true; do
        read -r -p "Checkmk site name [dmc]: " site
        site="${site:-dmc}"
        if [[ "$site" =~ ^[A-Za-z][A-Za-z0-9_]{0,15}$ ]]; then break; fi
        echo "Invalid: ..."
    done
    set_val CMK_SITE_ID "$site"
    summary+=("CMK_SITE_ID: set ($site)")
fi
```
Copy with `^[1-9][0-9]{0,17}$`, no default. Generated secrets (MQTT_BRIDGE_PASSWORD) go in the existing `for key in ...; gen_secret` list at lines ~58-67.

### `scripts/mqtt_poller.py` (publisher, pub-sub)

**Analog:** itself.

**Site id config + validation** (lines 435-460, 645-663): `_env_int/os.environ.get(...)` in `PollerConfig.from_env`, then `set_site_id()` raising `RuntimeError` on a bad value so startup fails instead of publishing a malformed topic. Mirror for `site_sen` with the regex from RESEARCH Code Examples (add `SITE_SEN` and `CLOUD_METRICS_HEARTBEAT_S` fields via `_env_int`/`_env_float`).

**Single publish choke point** (lines 2833-2849), extend with `event_id`:
```python
def _publish_json(client, topic, payload, qos, retain) -> None:
    try:
        client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
    except (TimeoutError, OSError) as exc:
        _logger.warning("Failed to publish to %s: %s", topic, exc)
```
Add optional `event_id=None` and `properties=` per RESEARCH Pattern 2; keep the except clause. Also embed `event_id` in the JSON payload (RESEARCH A1 belt and braces).

**Client constructors** (line 2802 and line 3343, two sites):
```python
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
```
Change both to `protocol=mqtt.MQTTv5`; `will_set`/`on_connect(client, userdata, flags, reason_code, properties=None)` signatures already fit VERSION2. Existing test `tests/test_mqtt_poller.py:2090` asserts `Client.assert_called_once_with(VERSION2)` and will need updating.

**Status publish** (lines 2852-2882): `publish_device_status` is QoS 0 retained, called every cycle. Throttle by a decision function in the caller (`run_cycle`, ~3391-3561) using new `PollerState` fields beside `last_status: dict[str, str]` (line 3031; initialised in line ~3380 `last_status={}`). Keep `publish_device_status` itself signature-stable.

**History** (`build_history_rows` line 2328 untouched; `write_history` line 2422): `write_history` returns early when `config.clickhouse_url` is unset and wraps each table in its own try/except with a never-raises contract. Copy that loop shape for the MQTT path:
```python
for table, rows in (("history.metrics", batch.metrics), ("history.host_state", batch.host_state), ("history.service_state", batch.service_state)):
    try: ...
    except ...: _logger.warning(...)
```
Publish to `site_topic(f"history/{table_short}")` QoS 1, retain False, chunked at ~500 rows, `event_id = f"{cycle_epoch}-{table}-{idx}"`.

### `analytics/topics.py` and `analytics/service.py` / `analytics/config.py`

**Topics analog:** `analytics/topics.py` lines 14-48 (`set_site_id` builds `_site_prefix = f"sites/{site_id}/"`, `site_topic`, `relative_topic`). `tests/test_analytics_topics.py` equality-tests these against the poller copies, so change both consistently. Add an optional prefix override (RESEARCH Pitfall 4) so `app/<SEN>/<site>/` works.

**Config analog:** `analytics/config.py` lines 200-215 `from_env` uses `os.environ.get(...)` plus `_env_int/_env_float`. Add `SITE_SEN` / topic prefix fields the same way.

**Client analog:** `analytics/service.py:197-216` `build_client`:
```python
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(config.mqtt_username, config.mqtt_password)
client.on_connect = service.on_connect
client.on_message = service.on_message
client.reconnect_delay_set(min_delay=1, max_delay=120)
client.connect(config.mqtt_host, config.mqtt_port, keepalive=30)
```
Docstring says clean session by design and subscriptions are re-issued in `on_connect`; the history subscriber needs `clean_start=False` plus SessionExpiryInterval, and the docstring must be updated. Existing dedupe precedent: `fetch_recent_event_keys` (analytics, events).

### `src/checkmk_wizard/wizard.py` (SITE_SEN prompt)

**Analog (prompt):** `phase1_site_bringup` site-name prompt via `_prompt_new_site_name(..., default=os.environ.get("CMK_SITE_ID", ""))` (~lines 500-512), and module regex constants `_SITE_NAME_RE` etc. (wizard.py:63-83) with `_password_problems`-style validators returning problem lists (123-136).
**Analog (env guidance):** `_print_automation_secret_created` (367-395) and the `CMK_PUBLIC_HOST` messaging (3059-3075) show the "edit deploy/.env, then recreate the container" operator wording; reuse for the `down/up` note. Repo-root-relative path convention: `Path(__file__).resolve().parents[2]` (wizard.py:40). Add `_SEN_RE = re.compile(r"[1-9][0-9]{0,17}")` named in the `_XXX_RE` convention. Best-effort rule: failure to write `.env` must fall back to printing the line for the operator, never abort.

### `tests/test_mosquitto_bridge_render.py` (new)

**Analog:** `tests/test_mosquitto_acl.py`: `_render(tmp_path, site)` helper running `sh SCRIPT TEMPLATE out` via `subprocess.run(..., env=..., capture_output=True, check=False)` with `CMK_SITE_ID` stripped from env (lines 22-34); parametrized valid/invalid ids asserting `returncode != 0`, `not out.exists()`, and `not list(tmp_path.iterdir())` (no temp leftovers, lines 105-114); `test_compose_wires_the_renderer` string-asserts compose (117-126). Copy for SEN cases (`0`, `007`, `-1`, `abc`, empty, `1 2`).

## Shared Patterns

### Validate-before-render for broker config
**Source:** `deploy/render-mosquitto-acl.sh` lines 15-52. **Apply to:** bridge renderer, init-env.sh SEN, wizard SEN, poller startup. Same regex everywhere (`[1-9][0-9]*`); topic segments reaching the archive must be non-empty (poller `is_publishable_device_id`, mqtt_poller.py ~690).

### Best-effort publish
**Source:** `_publish_json` (mqtt_poller.py:2833). Never raise out of the poll loop; catch `(TimeoutError, OSError)` and log a warning.

### Env config
**Source:** `PollerConfig.from_env` / `AnalyticsConfig.from_env`. New knobs (`SITE_SEN`, `CLOUD_METRICS_HEARTBEAT_S`, `HISTORY_PUBLISH_INTERVAL_S`) use the same `os.environ.get` + `_env_int/_env_float` helpers, and compose passes them as `${VAR:-default}`.

### Dated why-comments
Per CLAUDE.md: comment with why and verification source (live test, man page URL), as in the compose mosquitto entrypoint comments.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| Mosquitto bridge connection block | config | pub-sub | No bridge exists anywhere in the repo; use RESEARCH Pattern 1 and the mosquitto man page |
| MQTT v5 user-property publish, `clean_start`/session expiry | service | pub-sub | Repo is entirely v3.1.1 today; use RESEARCH Pattern 2, verify paho 2.1 API via context7. Closest live reference for verification: `scripts/smoke_test_broker.py` |
| Dashboard staleness and `config.json` SEN (`dashboard-react/src/lib/staleness.ts`, nginx envsubst config) | utility | transform | Not read by this mapping (frontend); planner should read `staleness.ts` (`isPollerStale` exists unused) before assigning |
| Cloud-side history subscriber dedupe | service | event-driven | Only the events-key dedupe precedent exists (`fetch_recent_event_keys`) |

## Conventions

Derivation via `gsd-tools verify conventions` was not run in this read-only mapping pass; the observations below come from the files read.

| Axis | Dominant | Share | Entropy | Status |
|------|----------|-------|---------|--------|
| File-name casing | snake_case (`mqtt_poller.py`, `render-mosquitto-acl.sh` uses kebab for deploy shell/config) | high in Python | low | named contract (kebab for `deploy/` scripts, snake for Python) |
| Identifier casing | snake_case functions, UPPER_SNAKE constants, `_XXX_RE` regexes | high | low | named contract |
| Export style | CJS/Python module-level public names; private `_` prefix | n/a | low | named contract |
| Import style | `from __future__ import annotations` first in every Python module | high | low | named contract |

**Contested hotspots (author's choice):** the CJS<->SDK dual resolver (`bin/lib/**` CJS `module.exports`/`require`; `sdk/src/**` ESM `export`/`import`) is the intentional contested split; each half is internally consistent per directory. Match the directory's local style. Not relevant to this phase's Python and shell files.

## Metadata

**Analog search scope:** `deploy/`, `scripts/mqtt_poller.py`, `analytics/`, `src/checkmk_wizard/wizard.py`, `tests/test_mosquitto_acl.py`
**Files scanned:** ~10 (targeted reads)
**Pattern extraction date:** 2026-10-14
