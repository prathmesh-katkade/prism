# Cortex information inventory — Step 1

The `before/` images record the Wave 1 Cortex at 1440 × 900. This inventory describes the information carried by that view and where it appears after the 3D renderer is removed.

| Information in the 3D view | Step 1 location |
| --- | --- |
| Run identity, plan state, and whether an investigation exists | Ledger heading and run record; the workspace and inspector retain the current run. |
| Count of real graph nodes and relations | Ledger heading and the node and relation disclosures. |
| Node kind, label, persisted state, and source identifier | All graph nodes list; select a row for its detail. Text state accompanies its tone. |
| Tone derived from persisted state (idle, active, recorded/completed, blocked/failed/cancelled) | Each node and group row has a `data-tone` cue and a written state. The tone mapping remains in `atlas-cortex-shared.ts`. |
| Dataset revision, assigned specialists and their steps/tools, and deduplicated evidence/output records | Records by role groups, derived from the stored graph and run plan. Every atomic node remains in the list, including nodes outside a group. |
| Group member node IDs and relation IDs | Selected group membership detail in the ledger; the data projection remains in `buildCortexGroups`. |
| Directed recorded relations and their relation types | Recorded relations list, with source, type, target, and edge ID. |
| Memory distinguished from other evidence | Memory label and kind in the atomic node list and context inspector. |
| Core, node, group, and pipeline focus | Focus controls and plan pipeline buttons still drive the context inspector. Selection changes the reading focus, not stored data. |
| Plan-step connection for specialist, tool, and plan-step nodes | `connectedStepIdForNode` remains in the data module; the plan and inspector show the recorded step. |
| Grounded answer and evidence | Result panel in the ledger and evidence in the inspector. |

The 3D position, camera, zoom, bloom, glow, particles, and rotation conveyed no additional stored fact. They are removed. Step 2 may refine the presentation of long records and cross-link navigation after screenshot review; no information above is deferred.
