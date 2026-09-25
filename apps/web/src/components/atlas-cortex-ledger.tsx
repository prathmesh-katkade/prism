"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { AtlasRunResponse, CortexGraphState, CortexNode } from "@prism/api-contracts";
import { buildCortexGroups, cortexTone, isMemoryNode, type CortexGroup, type CortexSelection } from "./atlas-cortex-shared";

/** A readable projection of the stored Cortex graph. Selection never creates a node or relation. */
export function AtlasCortexLedger({ graph, run, selectedStepId, onSelectStep, onSelectNode, stageOverlay, initialFocusNodeId }: {
  graph: CortexGraphState | null;
  run: AtlasRunResponse | null;
  selectedStepId: string | null;
  onSelectStep(stepId: string): void;
  onSelectNode?(selection: CortexSelection): void;
  stageOverlay?: ReactNode;
  initialFocusNodeId?: string | null;
}) {
  const nodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const edges = graph?.edges ?? [];
  const groups = useMemo(() => buildCortexGroups(graph, run), [graph, run]);
  const [focus, setFocus] = useState<string | null>(null);
  useEffect(() => { setFocus(null); }, [run?.run_id]);

  function selectNode(node: CortexNode) {
    setFocus(node.node_id);
    onSelectNode?.({ kind: "node", node });
  }
  function selectGroup(group: CortexGroup) {
    setFocus(group.groupId);
    onSelectNode?.({ kind: "group", group });
    if (run && group.kind === "specialist") {
      const steps = (run.plan.steps ?? []).filter((step) => step.specialist === group.sourceId);
      const step = steps.find((item) => item.state === "running") ?? steps.find((item) => item.state === "blocked") ?? steps.find((item) => item.state === "failed") ?? steps[0];
      if (step) onSelectStep(step.step_id);
    }
  }
  function selectCore() {
    setFocus(nodes.find((node) => node.kind === "run")?.node_id ?? null);
    onSelectNode?.({ kind: "core" });
  }
  useEffect(() => {
    if (!initialFocusNodeId) return;
    const match = nodes.find((node) => node.node_id === initialFocusNodeId) ?? nodes.find((node) => node.kind === "plan_step" && node.source_id === initialFocusNodeId);
    if (match) selectNode(match);
  }, [initialFocusNodeId, nodes, run?.run_id]);

  const focusedNode = nodes.find((node) => node.node_id === focus);
  const focusedGroup = groups.find((group) => group.groupId === focus);
  const selectionDetail = focusedNode
    ? { kind: isMemoryNode(focusedNode) ? "memory" : focusedNode.kind.replaceAll("_", " "), label: focusedNode.label, state: focusedNode.state, detail: focusedNode.source_id }
    : focusedGroup
      ? { kind: focusedGroup.kind, label: focusedGroup.label, state: focusedGroup.status, detail: `${focusedGroup.memberNodeIds.length} real nodes · ${focusedGroup.memberEdgeIds.length} real relations` }
      : null;
  const heading = !run ? "No investigation selected" : run.plan.state === "completed" ? "Investigation complete" : `Investigation ${run.plan.state ?? "ready"}`;
  const labelById = new Map(nodes.map((node) => [node.node_id, node.label]));

  return (
    <section className="cortex-ledger" aria-label="Cortex real-state graph">
      <header className="cortex-ledger-heading">
        <div><span className="eyebrow">ATLAS · RUN RECORD</span><h2>{heading}</h2>
          <p>{run ? `${nodes.length} real nodes · ${edges.length} real relations` : "Start an investigation to inspect its stored run, plan, evidence, and relations."}</p>
          {run ? <code>{run.run_id}</code> : null}</div>
        {run ? <button type="button" className="cortex-run-focus" onClick={selectCore} aria-pressed={focus === nodes.find((node) => node.kind === "run")?.node_id}>Focus {heading}</button> : null}
      </header>
      {stageOverlay}
      {groups.length ? <section className="cortex-ledger-groups" aria-label="Cortex groups">
        <div className="cortex-ledger-section-title"><h3>Records by role</h3><p>Groups retain their member node and relation IDs.</p></div>
        <ul className="cortex-group-list" aria-label="Cortex satellites">{groups.map((group) => <li key={group.groupId}>
          <button type="button" data-tone={group.tone} aria-pressed={focus === group.groupId} onClick={() => selectGroup(group)} aria-label={`Focus ${group.label}`}>
            <span className="cortex-group-kind">{group.kind}</span><strong>{group.label}</strong><span className="cortex-group-status">{group.status}</span>
            <small>{group.memberNodeIds.length} nodes · {group.memberEdgeIds.length} relations</small>
          </button>
        </li>)}</ul>
      </section> : null}
      {selectionDetail ? <dl className="cortex-detail" aria-label="Selected Cortex node">
        <dt>Kind</dt><dd>{selectionDetail.kind}</dd><dt>Label</dt><dd>{selectionDetail.label}</dd>
        <dt>State</dt><dd>{selectionDetail.state}</dd><dt>Source / membership</dt><dd className="acc-mono">{selectionDetail.detail}</dd>
      </dl> : null}
      {focusedNode ? <p className="cortex-ledger-ids">Node ID: <code>{focusedNode.node_id}</code></p> : null}
      {focusedGroup ? <div className="cortex-ledger-ids" aria-label="Selected group membership">
        <p>Member node IDs: {focusedGroup.memberNodeIds.map((id) => <code key={id}>{id}</code>)}</p>
        <p>Relation IDs: {focusedGroup.memberEdgeIds.length ? focusedGroup.memberEdgeIds.map((id) => <code key={id}>{id}</code>) : "None recorded"}</p>
      </div> : null}
      {nodes.length ? <details className="cortex-atomic-disclosure" open>
        <summary>All graph nodes ({nodes.length})</summary>
        <ul className="cortex-node-list" aria-label="Cortex nodes">{nodes.map((node) => {
          const collidesWithGroup = groups.some((group) => group.label === node.label);
          const selectedStep = node.kind === "plan_step" && node.source_id === selectedStepId;
          return <li key={node.node_id}><button type="button" data-tone={cortexTone(node.state)} aria-pressed={focus === node.node_id} data-linked-step={selectedStep} onClick={() => selectNode(node)} aria-label={`${collidesWithGroup ? "Focus atomic node" : "Focus"} ${node.label}`}>
            <span className="cortex-node-kind">{isMemoryNode(node) ? "memory" : node.kind.replaceAll("_", " ")}</span>
            <strong>{node.label}</strong><span className="cortex-node-state">{node.state.replaceAll("_", " ")}</span>
          </button></li>;
        })}</ul>
      </details> : null}
      {edges.length ? <details className="cortex-relations"><summary>Recorded relations ({edges.length})</summary>
        <ol>{edges.map((edge) => <li key={edge.edge_id}><span>{labelById.get(edge.source_node_id) ?? edge.source_node_id}</span><small>{edge.relation.replaceAll("_", " ")}</small><span>{labelById.get(edge.target_node_id) ?? edge.target_node_id}</span><code>{edge.edge_id}</code></li>)}</ol>
      </details> : null}
      {run ? <p className="cortex-ledger-note">State and membership come from this run’s stored graph. A selection changes the reading focus only.</p> : null}
    </section>
  );
}
