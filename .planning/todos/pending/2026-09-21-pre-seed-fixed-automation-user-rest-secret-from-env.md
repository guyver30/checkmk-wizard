---
created: 2026-09-21T13:48:04.553Z
title: Pre-seed fixed automation-user REST secret from env
area: api
files:
  - src/checkmk_wizard/api.py:386-524 (bootstrap_automation_user)
  - src/checkmk_wizard/wizard.py:295-310 (_print_automation_secret_created)
  - deploy/compose.yaml (CMK_PASSWORD / CMK_REST_SECRET env wiring)
  - deploy/.env.example
---

## Problem

Today, provisioning the Checkmk `automation` REST user's secret requires a manual hand-off:
`bootstrap_automation_user()` (`api.py:432`) generates a random secret
(`secrets.token_urlsafe(24)`) and POSTs it to Checkmk when creating the user. The wizard
prints that secret to the console (`_print_automation_secret_created`, `wizard.py:295`) and
the operator must manually copy it into `deploy/.env` as `CMK_REST_SECRET` so the
`poller`/`worker` containers can authenticate — this is unavoidable today only because
nothing pushes a pre-chosen value into Checkmk ahead of time.

This mirrors how `CMK_PASSWORD` already works for `cmkadmin`: `deploy/compose.yaml` hardcodes
it in a gitignored `.env`, and the Checkmk container's own entrypoint uses that env var
directly to set `cmkadmin`'s GUI login password at startup — no generate-then-copy step
exists for that credential.

## Solution

Have `bootstrap_automation_user()` read a fixed `CMK_REST_SECRET` from the environment (the
same var already consumed by the `poller`/`worker` compose services) instead of generating a
random one, and push that value into Checkmk's REST API on user creation. This eliminates the
current "generate → print → hand-copy into `deploy/.env`" step entirely — the value is already
known ahead of time.

**Key design point (must not skip):** the wizard currently only ever *creates* the automation
user (a fresh POST). Re-running the wizard against a site where `automation` already exists
must instead PUT/update the existing user's secret to match the fixed `.env` value, or a site
recreate/restore could leave Checkmk's stored secret out of sync with what `deploy/.env`
still says. Needs idempotency handling, not just a swap from random-generate to fixed-read.

Same disposable-credential threat model as `CMK_PASSWORD` already accepted in this project
(gitignored `.env`, local/on-prem, rotate before exposing beyond a trusted LAN) — no new
security posture required.
