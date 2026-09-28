---
created: 2026-09-28T00:00:00.000Z
title: Revisit the criticality and dependency model (not working as the operator expects)
area: poller + dashboard
files:
  - scripts/mqtt_poller.py (_effective_criticality_index, _dependents_closure, incident worst_criticality)
  - dashboard-react/src/components/CriticalityEditor.tsx
  - dashboard-react/src/components/IncidentCard.tsx
  - .planning/phases/14-fleet-intelligence/14-CONTEXT.md (D-09, D-15, D-04)
---

## Problem

During the 14-09 live UAT (2026-09-28), the operator said the criticality and dependency behaviour
"is not really working as I expect, and still unclear", and chose to park it and revisit it later.

## What was observed (step 6)

- Setup: `.200` set to criticality `critical`, depending on `.204`. `.204` was also `critical`
  (left over from step 2). `.204` was faked DOWN.
- Result: one incident card for `.204`, badge `critical`, with `.200` listed under
  "Dependent devices". `.200` stayed OK in the map and the device tree.
- This matches the code: the badge came from `.204`'s own tier. D-15's one-tier drop for a
  still-UP dependent was hidden by that. D-15 also deliberately gives the dependent no
  marker in the map or tree.
- Worked as expected: the editor (steps 2-3), long `depends_on` labels stored unmodified in
  Checkmk (step 4, 13 hosts), and the poller carrying the new label keys (step 5).

## To discuss when revisiting

- What the operator expects to see for a dependent host (a map or tree marker? a state?).
- Whether the "one tier lower" rule (D-15) and the single worst-tier badge are the right model,
  or whether the card should say where the tier comes from (root vs dependent).
- How host criticality and per-service criticality should interact.
- Probably best handled as a discuss-phase and then a new or decimal phase, not a quick task.

## Code review findings to fix as part of the rework (14-REVIEW.md, 2026-09-28)

- **WR-01:** a failed optimistic write in `CriticalityEditor` rolls back a stale value. It can land in
  another host's panel, or overwrite a later successful write. Key the panel by host and guard
  rollbacks with a per-field write sequence.
- **WR-02:** the TypeScript `parseServiceCriticalityLabel` doesn't trim whitespace (the Python parser
  does) and has no 200-entry cap. A hand-edited entry like `sshd = critical` is silently deleted on
  the next per-service write.
- **WR-03:** the editor offers service rows whose names contain `:`, `;` or `=`, which the writer
  always rejects. The error wrongly says "Checkmk rejected the update".
- **WR-05:** the "won't take effect until Apply changes" wording (confirm dialog, README, deployment
  doc) is probably false. The poller reads labels from REST `host_config`, which likely includes
  unactivated changes. Live-verify, then fix the wording.
- **IN-02:** `service_criticality` is written, parsed and published, but nothing uses it.
