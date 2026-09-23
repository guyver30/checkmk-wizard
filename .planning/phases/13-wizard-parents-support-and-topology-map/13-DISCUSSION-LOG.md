# Phase 13: Wizard Parents Support and Topology Map - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-23
**Phase:** 13-wizard-parents-support-and-topology-map
**Areas discussed:** Parent detection method (redefined to write-back path), vis-network
integration approach, Map interaction & grouping behavior

---

## Todo fold check

| Option | Description | Selected |
|--------|-------------|----------|
| Leave it out | Pending todo "Pre-seed fixed automation-user REST secret from env" scored 0.9 by keyword match, but is about Phase 1 bootstrap credentials, unrelated to parents/topology | ✓ |
| Fold it in | Add REST secret pre-seeding to Phase 13's scope | |

**User's choice:** Leave it out.

---

## Parent detection method (redefined mid-discussion)

| Option | Description | Selected |
|--------|-------------|----------|
| Manual pick, mirrors device_type | Phase 4 prompt, pick parent from onboarded NetworkDevice hosts | |
| Auto-guess from subnet gateway + override | Scanner probes gateway IP, proposes default | |
| Free-text hostname entry | Plain text prompt, no validation | |

**User's choice:** None of the above — redirected entirely: "I think doing this on the
wizard is not UI friendly. I have a better idea: network map in dashboard with edit mode.
So when starts fresh, it just place hosts there, not overlapping (like in a grid). User will
draw lines between hosts to define relations, and eventually add unmanaged LAN switch if
there's no managed switches as hosts. Then this will update the parent/child relationship in
checkmk, and eventually saved locally as well."
**Notes:** This single answer reshaped the entire phase from a wizard-CLI feature to a
dashboard-edit-mode feature. Became CONTEXT.md D-01.

### Ordering (parent must exist before being referenced)
**User's choice:** Deferred to the network-map redesign — no longer applicable once parent
capture moved out of the wizard's sequential onboarding flow.

### Retroactive correction for already-onboarded hosts
**User's choice:** "if they have parent relation, then create links. If not, just place them
on the map without overlap (like in a grid) so they can be positioned and lines can be
drawn." — folded into D-01; no separate Phase-10.1-style bulk-correction screen needed since
the map itself IS the correction UI for every host, old or new.

### Write-back mechanism
| Option | Description | Selected |
|--------|-------------|----------|
| Browser calls Checkmk REST API directly | Simplest, truly live; embeds a write credential client-side | ✓ |
| Edit mode stages changes, wizard applies them | No browser credential exposure, but not live | |
| New tiny local write-proxy service | Most secure, but violates "no new backend" constraint | |

**User's choice:** Browser calls Checkmk REST API directly.
**Notes:** Became D-04. Flagged that the credential should be narrowly-scoped, not the
wizard's own full-power automation user — open item for research/planning.

### Unmanaged switch representation
| Option | Description | Selected (first pass) | Selected (revised) |
|--------|-------------|:---:|:---:|
| Onboard as real Checkmk ping-only host | Reuses existing "ping" os_family path | | |
| Dashboard-only synthetic node, never sent to Checkmk | Purely visual, no real `parents` edge | ✓ (first answer) | |

**User's first choice:** Dashboard-only synthetic node.
**User's revision (next question):** "it can be a host in checkmk topology, but it shouldn't
be monitored in terms of ping or others, as it's not pingable. So I don't want to see warns /
critic because of this." — reversed to: real Checkmk host, one per switch, monitoring
suppressed. Became D-05/D-06.

**Follow-up — no-check host shape:**
| Option | Description | Selected |
|--------|-------------|----------|
| No-IP, no-agent host | Nothing for Checkmk to check by construction; needs live verification | ✓ |
| Has IP, PING disabled via rule | Leaves door open for future SNMP; more moving parts | |

### Position persistence ("saved locally")
| Option | Description | Selected |
|--------|-------------|----------|
| Per-browser localStorage | Matches D-32 precedent, but not shared across viewers | |
| Shared via retained MQTT topic | Consistent across viewers, but reopens the broker-ACL write-access question ROADMAP flagged as unsolved | |

**User's choice:** Neither listed option — asked "can this layout be stored in the container
volume?" Resolved (via the already-agreed direct-REST-write path) as a new Checkmk custom
host attribute (`map_position`), which durably lives on the `checkmk_data` volume without any
new infrastructure. Became D-07.

**Follow-up — where synthetic (non-Checkmk) node data lives:**
| Option | Description | Selected |
|--------|-------------|----------|
| One JSON blob on a dedicated sentinel host | Single owner, survives folder reorg | ✓ (superseded) |
| One JSON blob on the root folder `/` | No extra host clutter | |

**Note:** This question was answered "sentinel host," but immediately superseded by the next
answer (unmanaged switches becoming real per-switch hosts), which made the sentinel-blob
approach unnecessary — D-05/D-07 together cover it with no separate mechanism.

---

## vis-network integration approach

### pyvis + networkx evaluation (user's explicit ask)
**Claude's assessment presented:** pyvis generates static, self-contained HTML from Python
(one-shot, no live-update API, wraps vis.js internally); networkx is a graph-algorithms/
layout library with no browser rendering. Neither fits a live, client-side, MQTT-driven React
SPA, and both would require server-side Python rendering, conflicting with the no-new-backend
constraint.

| Option | Description | Selected |
|--------|-------------|----------|
| Proceed with vis-network | Matches already-locked Phase 11 D-08/D-09; also what pyvis itself wraps | |
| Something else — explain | | |

**User's response:** Neither listed option directly — asked "can vis-network support svg
icons and coloring of these icons based on host status?" (a clarifying question, not a
rejection). Answered below; vis-network confirmed as the library.

### Delivery mechanism
| Option | Description | Selected |
|--------|-------------|----------|
| npm dependency | `npm install vis-network`, thin React wrapper; matches `mqtt`'s existing precedent | ✓ |
| Vendor UMD build | Follows ROADMAP's original (pre-React-rewrite) instruction literally | |

**User's choice:** npm dependency.

### Edit-mode UI
| Option | Description | Selected |
|--------|-------------|----------|
| Built-in manipulation toolbar | addEdge/editEdge/deleteEdge callbacks, less custom code | ✓ |
| Fully custom interaction | More control, reimplements existing functionality | |

**User's choice:** Built-in manipulation toolbar.

### Rendering technique (SVG icons + status coloring)
| Option | Description | Selected |
|--------|-------------|----------|
| circularImage + recolored SVG data-URI | Simpler, no custom canvas draw code | ✓ |
| ctxRenderer, pixel-parity with Tree/StateBadge | More code, exact visual match | |

**User's choice:** circularImage + recolored SVG data-URI.

### Icon source and location
| Option | Description | Selected |
|--------|-------------|----------|
| Reuse existing vendored KONE SVG set | Same icons already used in tree/badges, zero new dependency | |
| lucide-react or tabler icons | Wider selection, visually inconsistent unless style-matched | |

**User's choice:** Neither listed option directly — "I will curate the svg and place them
related to device type somewhere in the project folder. Tell me where." Claude proposed
`dashboard-react/src/assets/icons/device-types/` with Vite `?raw` imports, keeping the
existing lowercase-kebab filenames from the pre-React vendored set as a starting point. User
confirmed: "Yes, src/assets/icons/device-types/ with ?raw imports." Became D-09.

---

## Map interaction & grouping behavior

### Click-through to details
| Option | Description | Selected |
|--------|-------------|----------|
| Yes, matches DASH-11 tree click pattern | Consistent with existing app | ✓ |
| No click-through | Map view-only otherwise | |

**User's choice:** Yes.

### Grouping toggle applying to the map
| Option | Description | Selected |
|--------|-------------|----------|
| Map stays flat, edges only | Grouping overlay would compete visually with real edges | ✓ (with addition) |
| Grouping toggle also drives the map | More complexity, no existing precedent for graph clustering | |

**User's choice:** Map stays flat, BUT with an important addition: "I would like to have
different tabs to visualize specific map based on high level location (the additional tag I
talked about before, scheduled for later phase). Like tower1, tower2, tower3, etc. Also the
map should group the hosts with just a rectangle showing the secondary location... also this
part of new tagging to be done in later phase. But prepare the map for this."
**Notes:** Tower tabs and sub-location rectangles map directly to the already-parked Phase 15
(Location Hierarchy for Hosts and Dashboard Tower Tabs, per STATE.md). Not implemented in
Phase 13 — captured as D-11's forward-compatibility note and a Deferred item.

### Edit mode toggle
| Option | Description | Selected |
|--------|-------------|----------|
| Explicit "Edit topology" toggle | Matches manipulation module's own recommended pattern, avoids accidental kiosk edits | ✓ |
| Always editable | Simpler UI, but risk of accidental topology changes | |

**User's choice:** Explicit toggle.

---

## Claude's Discretion

- Exact grid-layout algorithm for initial node placement
- Exact `map_position` custom-attribute shape (one string vs. two attributes)
- Manipulation toolbar styling within kone-design-system's visual language
- Naming/location of the write-capable credential constant in `config.ts`

## Deferred Ideas

- Per-tower dashboard tabs and sub-location rectangle grouping — Phase 15 (parked).
- Whether `map_position` should be added to the poller's MQTT `lan/devices/topology` payload
  vs. staying a browser-direct-read-from-Checkmk concern — open question for research/planning.
- Exact Checkmk role/permission scope for the write-capable browser credential.
- REQUIREMENTS.md amendment covering the dashboard-edit-mode write-back capability (replaces
  the wizard-CLI requirement IDs ROADMAP.md had anticipated).
