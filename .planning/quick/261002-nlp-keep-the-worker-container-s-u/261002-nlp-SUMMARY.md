---
status: complete
---
# Quick 261002-nlp: keep the worker's uv venv out of the bind-mounted checkout

Symptom (deploy host): `uv run` in the checkout failed with `failed to canonicalize path .../.venv/bin/python3: Permission denied`.
Cause (inferred from the evidence, not reproduced here): the worker bind-mounts the checkout (`../..:/app`) and `deploy/run-wizard.sh` runs `uv sync` inside the container, which created `<checkout>/.venv` with a python symlink into the container's own uv Python (container /root). The host user cannot resolve that. The `.venv` seen later was rebuilt by the host (python3 -> /home/kone/.local/share/uv/python/...), and the next container `uv sync` would replace it again.
Fix: `UV_PROJECT_ENVIRONMENT=/opt/checkmk-wizard-venv` in the worker's environment (compose.yaml), plus a note and cleanup steps in docs/DEPLOY-NEW-MACHINE.md.
Not verified live: on the deploy host, `git pull`, `rm -rf .venv`, full `podman compose down && up -d`, then `deploy/run-wizard.sh` (rebuilds the venv in the container) and a host `uv sync && uv run pytest -q` should both work and stop replacing each other's `.venv`.
