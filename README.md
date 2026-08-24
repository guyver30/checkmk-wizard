# checkmk-wizard

Interactive terminal wizard that configures a fresh Checkmk Community Edition
site from scratch — network discovery, host onboarding, agent installation,
and activation. See [docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md](docs/CHECKMK_SETUP_CONFIGURATOR_PLAN.md)
for the full design and phase breakdown.

For exactly how the implementation behaves today, see
[docs/WIZARD-OPERATION.md](docs/WIZARD-OPERATION.md). For how that
implementation compares to the plan above (verified against live Checkmk
docs), see [docs/PLAN-CONFORMANCE-AUDIT.md](docs/PLAN-CONFORMANCE-AUDIT.md).

## Setup

```bash
uv sync
```

## Run

```bash
uv run checkmk-wizard
```

Run this directly on the Checkmk host — it drives `omd`/site bootstrap
locally and needs local filesystem access to read the automation user's
secret.

## Test

```bash
uv run pytest
```

Tests cover the REST API client (mocked via `respx`), the async port
scanner, and the remote (SSH/firewall/OS-compatibility) helpers in
isolation. They don't exercise a live Checkmk site, real network targets,
or actual SSH connections — that requires a real lab environment.

## Project layout

- `src/checkmk_wizard/api.py` — Checkmk REST API client (Phase 1, 2, 5-7)
- `src/checkmk_wizard/site.py` — OMD site bootstrap and automation credentials (Phase 1)
- `src/checkmk_wizard/scanner.py` — async TCP port scanner (Phase 3)
- `src/checkmk_wizard/remote.py` — SSH firewall check/fix and agent install (Phase 5.1/5.2)
- `src/checkmk_wizard/livestatus.py` — post-activation host state check (Phase 7)
- `src/checkmk_wizard/wizard.py` — interactive orchestration of all phases
