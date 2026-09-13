/**
 * Data-layer contract shared by every Cortex presentation. This module owns
 * no rendering: it maps the durable `CortexGraphState` / `AtlasRunResponse`
 * onto plan-step selection and stable spatial layout, so a presentation
 * layer (2D SVG, 3D scene, or a future replacement) can be swapped without
 * touching the truthfulness or determinism rules that live here.
 */
import type { AtlasRunResponse, CortexGraphState, CortexNode } from "@prism/api-contracts";
import type { PipelineStage } from "./atlas-run-activity";

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

/** The backend's Cortex graph has no dedicated "memory" node kind: a
 * persisted memory record surfaces as an EVIDENCE node whose label the
 * graph builder prefixes with "Memory:" -- the one real signal that
 * distinguishes it, carried over unchanged from the original SVG Cortex. */
export function isMemoryNode(node: CortexNode): boolean {
  return node.label.startsWith("Memory:");
}

/** What the unified context inspector is currently showing -- driven only
 * by a real click on the core, a real node, a real pipeline stage, or a
 * real grouped satellite, never a fabricated selection. */
export type CortexSelection = { kind: "core" } | { kind: "node"; node: CortexNode } | { kind: "pipeline"; stage: PipelineStage } | { kind: "group"; group: CortexGroup };

export type Vec3 = readonly [number, number, number];

/** Radius of the decorative pipeline ring, sized to sit between the core
 * and the innermost real-node ring (plan_step, at 1.7) without overlapping
 * either. */
export const PIPELINE_RING_RADIUS = 1.25;

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

// --- Grouped projection ------------------------------------------------------
//
// The reference layout is a *grouped* view: one satellite for the dataset,
// one per specialist this run actually assigned a step to, and one pooled
// evidence satellite -- not all ~19 atomic nodes drawn individually. This
// section derives that grouping from the same real `CortexGraphState` the
// atomic view uses; it never adds a relation the backend did not report,
// and every group keeps the exact real node_ids/edge_ids it stands in for
// so a caller can always recover full provenance instead of treating one
// drawn line as itself the fact (`memberNodeIds`/`memberEdgeIds`).

export type CortexGroupKind = "dataset" | "specialist" | "evidence";

export type CortexGroup = {
  groupId: string;
  kind: CortexGroupKind;
  label: string;
  /** Human status derived only from this group's own real member states
   * (e.g. "1 blocked step") -- never smoothed into a single verdict. */
  status: string;
  tone: CortexTone;
  /** specialist id / dataset source_id, or "evidence" for the pooled group. */
  sourceId: string;
  memberNodeIds: string[];
  memberEdgeIds: string[];
  /** Only set on the evidence group: the distinct real evidence_id count
   * (the same dedup rule buildEvidenceLineage/AtlasResultPanel use), since
   * one underlying evidence item can re-surface under several step-scoped
   * node_ids in the atomic graph. */
  distinctEvidenceCount?: number;
};

// analytical_object/artifact nodes are other durable records a run can
// produce; they read the same as "evidence" in a grouped view (recorded
// output, not an actor), so they pool into the evidence satellite rather
// than getting invented satellites of their own.
const EVIDENCE_LIKE_KINDS = new Set(["evidence", "analytical_object", "artifact"]);

function edgeIdsTouching(edges: CortexGraphState["edges"], ids: Set<string>): string[] {
  return (edges ?? []).filter((edge) => ids.has(edge.source_node_id) || ids.has(edge.target_node_id)).map((edge) => edge.edge_id);
}

/** Groups the real, already-fetched Cortex graph into the small set of
 * satellites the reference shows. Every plan_step/tool node folds into the
 * specialist group that owns it, by the exact same specialist/step
 * assignment `buildSpecialistActivity` reads from `run.plan.steps` --
 * never a second, independent notion of ownership. A node that matches no
 * bucket (there is currently no such real kind) is never silently
 * dropped: it stays reachable through the existing atomic node list and
 * chip row, which this function does not replace. */
export function buildCortexGroups(graph: CortexGraphState | null, run: AtlasRunResponse | null): CortexGroup[] {
  if (!graph) return [];
  const nodes = graph.nodes ?? [];
  const edges = graph.edges ?? [];
  const groups: CortexGroup[] = [];

  for (const node of nodes.filter((candidate) => candidate.kind === "dataset")) {
    const ids = new Set([node.node_id]);
    groups.push({ groupId: `group:dataset:${node.node_id}`, kind: "dataset", label: node.label, status: node.state, tone: cortexTone(node.state), sourceId: node.source_id, memberNodeIds: [...ids], memberEdgeIds: edgeIdsTouching(edges, ids) });
  }

  for (const node of nodes.filter((candidate) => candidate.kind === "specialist")) {
    const steps = run ? (run.plan.steps ?? []).filter((step) => step.specialist === node.source_id) : [];
    const memberIds = new Set([node.node_id]);
    for (const step of steps) {
      const stepNode = nodes.find((candidate) => candidate.kind === "plan_step" && candidate.source_id === step.step_id);
      if (stepNode) memberIds.add(stepNode.node_id);
      const toolNode = nodes.find((candidate) => candidate.kind === "tool" && candidate.source_id === step.tool_name);
      if (toolNode) memberIds.add(toolNode.node_id);
    }
    const blocked = steps.filter((step) => step.state === "blocked").length;
    const failed = steps.filter((step) => step.state === "failed").length;
    const cancelled = steps.filter((step) => step.state === "cancelled").length;
    const running = steps.some((step) => step.state === "running");
    let status: string;
    let tone: CortexTone;
    if (!steps.length) { status = "Idle"; tone = "idle"; }
    else if (running) { status = "Running"; tone = "active"; }
    else if (blocked) { status = `${blocked} blocked step${blocked === 1 ? "" : "s"}`; tone = "danger"; }
    else if (failed) { status = `${failed} failed step${failed === 1 ? "" : "s"}`; tone = "danger"; }
    else if (cancelled) { status = `${cancelled} cancelled step${cancelled === 1 ? "" : "s"}`; tone = "danger"; }
    else if (steps.every((step) => step.state === "completed")) { status = "Completed"; tone = "good"; }
    else { status = "Queued"; tone = "idle"; }
    groups.push({ groupId: `group:specialist:${node.node_id}`, kind: "specialist", label: node.label, status, tone, sourceId: node.source_id, memberNodeIds: [...memberIds], memberEdgeIds: edgeIdsTouching(edges, memberIds) });
  }

  const evidenceNodes = nodes.filter((candidate) => EVIDENCE_LIKE_KINDS.has(candidate.kind));
  if (evidenceNodes.length) {
    const distinctSourceIds = new Set(evidenceNodes.map((node) => node.source_id));
    const ids = new Set(evidenceNodes.map((node) => node.node_id));
    const tone: CortexTone = evidenceNodes.some((node) => node.state === "blocked" || node.state === "failed") ? "danger" : "good";
    const count = distinctSourceIds.size;
    groups.push({ groupId: "group:evidence", kind: "evidence", label: "Evidence", status: `${count} record${count === 1 ? "" : "s"}`, tone, sourceId: "evidence", memberNodeIds: [...ids], memberEdgeIds: edgeIdsTouching(edges, ids), distinctEvidenceCount: count });
  }

  return groups;
}

/** Deterministic satellite layout: dataset anchored upper-left and evidence
 * lower area (matching the reference), specialists (sorted by id, so the
 * same run always lays out the same way) spread across the arc between --
 * stable for a given group set rather than insertion order. */
export function cortexGroupPositions3D(groups: readonly CortexGroup[]): Record<string, Vec3> {
  const positions: Record<string, Vec3> = {};
  const dataset = groups.filter((group) => group.kind === "dataset");
  const specialists = [...groups.filter((group) => group.kind === "specialist")].sort((a, b) => a.sourceId.localeCompare(b.sourceId));
  const evidence = groups.filter((group) => group.kind === "evidence");
  const ordered = [...dataset, ...specialists, ...evidence];
  const radius = 2.7;
  const startAngle = Math.PI * 0.82; // upper-left
  const sweep = -Math.PI * 1.55; // arcs across the top/right down toward the bottom
  const total = ordered.length;
  ordered.forEach((group, index) => {
    const t = total <= 1 ? 0 : index / (total - 1);
    const angle = startAngle + sweep * t;
    const y = 0.55 - t * 1.05; // starts high (dataset), ends low (evidence)
    positions[group.groupId] = [Math.cos(angle) * radius, y, Math.sin(angle) * radius];
  });
  return positions;
}
