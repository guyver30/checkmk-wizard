# Quick 260925-jah: Rework Phase 3 discovery

Goal: Phase 3 returns hosts to promote = own scan + pending placeholders already in Checkmk.

- New site (no hosts): scan mandatory, no prompt.
- Existing site: scan prompt defaults to yes only if Phase 2 just added a folder with a subnet; declining still returns pending hosts.
- `_pending_hosts()`: name == ipaddress, no `cmk_wizard=onboarded` label, tag_agent in (None, no-agent), tag_snmp_ds in (None, no-snmp).
- Phase 5 (`_device_type_and_alias_attributes`) stamps label `cmk_wizard=onboarded` on every promoted host.
- Tests + docs (README, WIZARD-OPERATION.md).
