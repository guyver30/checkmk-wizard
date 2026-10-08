# Quick 261008-cto Summary

Wizard now ensures one global "Systemd single service" rule (inactive = CRIT) when a Linux host with expected services is onboarded.

## Commits
- 0a451a8: feat - `CheckmkClient.list_rules`, `_ensure_systemd_inactive_crit_rule`, wired in Phase 5 after `_create_service_discovery_rules`, tests
- docs commit: `docs/WIZARD-OPERATION.md` (rule description, existing-site note, JSON-safe ruleset list)

## Decisions
- value_raw encoded as plain JSON (`json.dumps`): int-only nested dicts, no tuple/list ambiguity; matches `create_rule`'s live-verified JSON note. Idempotency parser uses `ast.literal_eval` (Checkmk echoes Python repr).
- Match criteria for an existing rule: folder "/", no host_name condition, states.inactive == 2. Failure on list means no create (avoids duplicates).

## Verification
- `uv run pytest -q`: 1125 passed. No pre-existing phase5 test needed changes.
- `grep -c "await _ensure_systemd_inactive_crit_rule("` = 1; docs greps >= 1.
- ruff on the 4 touched files: 4 findings (I001, RET501, PLR1711 in tests/test_wizard.py; B023 in wizard.py ~1777), all pre-existing at HEAD (confirmed for test_wizard.py via stdin check of HEAD; the B023 line is not in code I touched). Not fixed (out of scope).
- Endpoint verification: Context7 unavailable. Read Checkmk 2.4.0 source on GitHub via curl (`cmk/gui/openapi/endpoints/rule/__init__.py`): `list_rules` with `ruleset_name` query param, collection `value`, `_serialize_rule` gives `extensions.folder` ("/" + path), `conditions` (None keys dropped), `value_raw` = repr(...). Ruleset id/keys taken from the plan (Checkmk docs), not re-fetched by me.
- NOTHING was live-verified against a Checkmk site; only mocked (respx) tests ran.

## Deviations
None. README.md has no wizard-rule list, so no mention added there (grep found only WIZARD-OPERATION.md and the historical audit).

## Operator checklist
1. Run Phase 5 for a Linux host with an expected service (or add the rule by hand on an existing site), then Activate changes.
2. Setup > Services > Service monitoring rules > "Systemd single service": exactly one rule in Main folder, inactive = CRIT; re-run adds no second.
3. Optional: `GET /objects/rule/{id}`, confirm `extensions.value_raw` matches what was sent.
4. On the host: `sudo systemctl stop <service>`; after the next check (~1 min) "Systemd Service <name>" is CRIT.
5. Dashboard shows CRIT and a failure need appears (analytics, ~15 s after poll).
6. `sudo systemctl start <service>`; service returns to OK, need clears.
