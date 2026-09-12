/**
 * Data-layer contract shared by every Cortex presentation. This module owns
 * no rendering: it maps the durable `CortexGraphState` / `AtlasRunResponse`
 * onto plan-step selection and stable spatial layout, so a presentation
 * layer (2D SVG, 3D scene, or a future replacement) can be swapped without
 * touching the truthfulness or determinism rules that live here.
 */
import type { AtlasRunResponse, CortexNode } from "@prism/api-contracts";

/** Maps a Cortex node back to the plan step it is really connected to, by
 * the exact rule the backend's own graph builder uses -- never a guess. */
export function connectedStepIdForNode(node: CortexNode, run: AtlasRunResponse): string | null {
  const steps = run.plan.steps ?? [];
  if (node.kind === "plan_step") return steps.some((step) => step.step_id === node.source_id) ? node.source_id : null;
  if (node.kind === "specialist") return steps.find((step) => step.specialist === node.source_id && step.state === "running")?.step_id ?? steps.find((step) => step.specialist === node.source_id)?.step_id ?? null;
  if (node.kind === "tool") return steps.find((step) => step.tool_name === node.source_id && step.state === "running")?.step_id ?? steps.find((step) => step.tool_name === node.source_id)?.step_id ?? null;
  return null;
}

/** The four honest states a Cortex node's persisted `state` string reduces
 * to for coloring -- never inferred activity, only what was recorded. */
export type CortexTone = "idle" | "active" | "good" | "danger";

const ACTIVE_STATES = new Set(["running", "active"]);
const GOOD_STATES = new Set(["completed", "recorded", "executed"]);
const DANGER_STATES = new Set(["blocked", "failed", "cancelled"]);

export function cortexTone(state: string): CortexTone {
  if (ACTIVE_STATES.has(state)) return "active";
  if (GOOD_STATES.has(state)) return "good";
  if (DANGER_STATES.has(state)) return "danger";
  return "idle";
}

export type Vec3 = readonly [number, number, number];

const RING_RADIUS: Record<string, number> = { plan_step: 1.7, specialist: 2.4, tool: 3.1, evidence: 3.9, dataset: 2.9, analytical_object: 3.4, artifact: 3.6 };
const RING_TILT_SEED: Record<string, number> = { plan_step: 0, specialist: 1.3, tool: 2.6, evidence: 3.9, dataset: 5.2, analytical_object: 0.7, artifact: 1.9 };

/** 3D layout: the same determinism guarantee as `positionFor2D` (grouped by
 * kind into concentric rings so specialists/tools/evidence read as distinct
 * orbital shells around the run core), keyed by node_id so callers never
 * need to re-derive index/total themselves. */
export function cortexPositions3D(nodes: readonly CortexNode[]): Record<string, Vec3> {
  const byKind = new Map<string, CortexNode[]>();
  for (const node of nodes) {
    const bucket = byKind.get(node.kind);
    if (bucket) bucket.push(node);
    else byKind.set(node.kind, [node]);
  }
  const positions: Record<string, Vec3> = {};
  for (const [kind, bucket] of byKind) {
    if (kind === "run") {
      for (const node of bucket) positions[node.node_id] = [0, 0, 0];
      continue;
    }
    const radius = RING_RADIUS[kind] ?? 2.7;
    const tiltSeed = RING_TILT_SEED[kind] ?? 4.4;
    const total = bucket.length;
    bucket.forEach((node, index) => {
      const angle = (index / Math.max(1, total)) * Math.PI * 2;
      const tilt = Math.sin(angle * 2 + tiltSeed) * 0.4;
      positions[node.node_id] = [Math.cos(angle) * radius, tilt, Math.sin(angle) * radius];
    });
  }
  return positions;
}
