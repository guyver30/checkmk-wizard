# checkmk-wizard

Takes a bare [Checkmk](https://checkmk.com) Community Edition install all the way to a fully onboarded,
monitored network, and then shows that network live: an interactive terminal wizard (network discovery, host
onboarding, agent installation, activation) plus a containerized stack that publishes Checkmk's state over
MQTT to a React dashboard with a live, editable topology map, history, forecasts and incident narration.

## Documentation

| Read this | For |
|---|---|
| [`docs/DEPLOY-NEW-MACHINE.md`](docs/DEPLOY-NEW-MACHINE.md) | **Deploy and operate the stack**: prerequisites, the order of the steps, what each script in `deploy/` does, settings, offline use, checks, updating, backup and restore, starting over, troubleshooting |
| [`docs/WIZARD-OPERATION.md`](docs/WIZARD-OPERATION.md) | **The wizard**: requirements, host-native and container mode, every phase, options (`--demo`, `--manage`), and the dashboard demo runbook |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | **How it fits together**: container roles, ports, data flow, the MQTT topic contract and the cloud archive contract |
| [`dashboard-react/README.md`](dashboard-react/README.md) | The dashboard: building it, runtime config, map editing, device-type icons, incidents, admin mode |
| [`design-system/USAGE.md`](design-system/USAGE.md) | The `kone-design-system` component library the dashboard is built on |
| [`docs/archive/`](docs/archive/) | Original design plan, plan-conformance audit and research notes; history, not current behaviour |

## What is in the repository

- `src/checkmk_wizard/` — the wizard (Python 3.11+, managed with [uv](https://docs.astral.sh/uv/)):
  `api.py` (Checkmk REST client), `site.py` (OMD site bootstrap), `scanner.py` (TCP and ICMP scan),
  `remote.py` (SSH firewall and agent install), `livestatus.py` (post-activation host state),
  `wizard.py` (orchestration of all phases).
- `deploy/` — `compose.yaml`, image build files and the operator scripts (`init-env.sh`, `run-wizard.sh`,
  `redeploy.sh`, `backup.sh`, `restore_backup.sh`, `reset-site.sh`).
- `scripts/` — the Livestatus-to-MQTT poller, smoke tests and diagnostic probes.
- `analytics/` — needs, forecasts, incident narration and the daily availability rollup.
- `dashboard-react/`, `design-system/` — the dashboard SPA and its component library.

## Quick start

**Containerized stack (recommended).** Follow [`docs/DEPLOY-NEW-MACHINE.md`](docs/DEPLOY-NEW-MACHINE.md). In short,
with rootless Podman installed and the repo cloned into `~/checkmk-stack/app/checkmk-wizard`:

```bash
deploy/init-env.sh                                   # secrets, site name, this machine's address
cd deploy && podman compose build dashboard worker   # while online; the worker image makes the wizard work offline
podman compose up -d
./run-wizard.sh                                      # the wizard, inside the worker container
podman compose down && podman compose up -d          # once, so the poller sees the new setup
```

Then open the dashboard on port 8090. Update later with `deploy/redeploy.sh`.

**Wizard directly on a Checkmk host** (host-native mode, as root; this is the only case that runs `uv` on the host):

```bash
uv sync
uv run checkmk-wizard
```

The mode is detected by whether `omd` is on `PATH`. Requirements, both modes and all options are in
[`docs/WIZARD-OPERATION.md`](docs/WIZARD-OPERATION.md).

## Test

```bash
podman exec automation-worker bash -c "cd /app/checkmk-wizard && uv run pytest"
```

(On a development machine with `uv` installed, plain `uv run pytest` from the checkout does the same.)

The tests cover the REST client (mocked with `respx`), the scanner and the remote (SSH, firewall,
OS-compatibility) helpers in isolation; they do not touch a live Checkmk site, real targets or SSH. The
dashboard has its own suite (`dashboard-react/`, see its README).
