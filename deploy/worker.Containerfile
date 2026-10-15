# Automation worker image: python:3.12-slim with uv and the wizard's dependencies
# baked in, so the wizard runs on a machine with no internet access.
#
# Before this file, the worker ran `pip install uv` at every container start and
# `run-wizard.sh` ran `uv sync` against PyPI, so an offline machine could not start
# the wizard ("uv: command not found", then "No matching distribution found").
#
# Build it ONCE while the machine is online (and again after a `git pull` that
# changes pyproject.toml or uv.lock):
#     cd deploy && podman compose build worker
# Afterwards `uv sync` / `uv run` in run-wizard.sh find everything locally:
# - the venv at /opt/checkmk-wizard-venv (the path compose.yaml already sets as
#   UV_PROJECT_ENVIRONMENT),
# - the managed Python 3.11 that .python-version asks for, in /opt/uv-python,
# - uv's wheel and build-backend cache in /opt/uv-cache.
# UV_OFFLINE=1 makes uv fail fast with a clear message instead of hanging when
# something is missing (typically: uv.lock changed since the image was built).
#
# Build context is the repo root (see the worker service's build: block); only
# pyproject.toml, uv.lock, .python-version, README.md and src/ are used.
# The project is copied to /app/checkmk-wizard so the editable install recorded
# in the venv points at the same path the bind mount provides at runtime.
FROM python:3.12-slim

ENV UV_PROJECT_ENVIRONMENT=/opt/checkmk-wizard-venv \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_CACHE_DIR=/opt/uv-cache \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv

WORKDIR /app/checkmk-wizard
COPY pyproject.toml uv.lock .python-version README.md ./
COPY src ./src
RUN uv sync --frozen

ENV UV_OFFLINE=1
