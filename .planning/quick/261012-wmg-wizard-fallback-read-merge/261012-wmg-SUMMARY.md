# Quick 261012-wmg: wizard host-update fallback read-merges

Fixed integration gap 2 from v1.0-MILESTONE-AUDIT: `_create_or_update_host`'s
create-collision fallback PUT only the wizard's attributes (a replace PUT), wiping
dashboard-set parents and labels on promotion. It now GETs the host, takes
`extensions.attributes`, drops `meta_data`, applies the wizard attributes over it,
merges `labels` key by key, and PUTs with the ETag. No ETag still re-raises.

Files: src/checkmk_wizard/wizard.py, tests/test_wizard.py (2 new tests),
docs/WIZARD-OPERATION.md.

Verification: `uv run pytest -q` 1253 passed; ruff shows the same 6 pre-existing
findings, none new. Mocked-test only (respx), NOT live-verified against Checkmk.

Other callers: the only other `update_host_attributes` call (wizard.py ~1312) already
read-merges; no further subset-PUT callers found.
