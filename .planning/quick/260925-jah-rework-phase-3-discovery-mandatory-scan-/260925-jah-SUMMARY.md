---
status: complete
---
# Quick 260925-jah Summary

Implemented inline in `src/checkmk_wizard/wizard.py` (`_pending_hosts`, `WIZARD_MARKER_LABELS`, reworked `phase3_discovery`, marker label in `_device_type_and_alias_attributes`). 506 tests pass (5 new). Docs updated: README.md, docs/WIZARD-OPERATION.md.

Not verified against a live Checkmk: that the daily-scan hosts appear in `list_hosts()` with `ipaddress` attribute and IP as name, and that a PUT on promotion drops `tag_criticality=offline`.
