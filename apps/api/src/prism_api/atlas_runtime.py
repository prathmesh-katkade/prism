"""Phase 10's first safe Atlas runtime.

Atlas may orchestrate only explicit deterministic PRISM tools.  Providers advise
planning capability; they never receive raw data or gain command execution.
"""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Optional, Protocol

from fastapi import HTTPException, status
from prism_api_contracts import (
    AtlasCouncilConclusion,
    AtlasEvidenceReference,
    AtlasModelProviderCapabilities,
    AtlasModelProviderName,
    AtlasPlanState,
    AtlasPlanStep,
    AtlasRunEvent,
    AtlasRunEventType,
    AtlasRunRequest,
    AtlasRunResponse,
    AtlasSpecialistId,
    AtlasSpecialistIdentity,
    AtlasStepKind,
    AtlasStepState,
    AtlasStructuredPlan,
    CortexEdge,
    CortexGraphState,
    CortexNode,
    CortexNodeKind,
)

from .overview import get_profile
from .transport import ServerSentEvent

SPECIALISTS: tuple[AtlasSpecialistIdentity, ...] = (
    AtlasSpecialistIdentity(specialist=AtlasSpecialistId.ATLAS, display_name="Atlas", role="Lead analytical orchestrator", speaks_to_user=True),
    AtlasSpecialistIdentity(specialist=AtlasSpecialistId.SCOUT, display_name="Scout", role="Dataset reconnaissance and profiling"),
    AtlasSpecialistIdentity(specialist=AtlasSpecialistId.STAT, display_name="Stat", role="Statistical methodology and experiment review"),
    AtlasSpecialistIdentity(specialist=AtlasSpecialistId.AUDITOR, display_name="Auditor", role="Independent evidence and methodology verifier"),
)


class AtlasModelProvider(Protocol):
    """A provider reports safe capability; tool execution never crosses this boundary."""

    def capabilities(self) -> AtlasModelProviderCapabilities:
        ...


class DeterministicAtlasProvider:
    def capabilities(self) -> AtlasModelProviderCapabilities:
        return AtlasModelProviderCapabilities(
            provider=AtlasModelProviderName.DETERMINISTIC,
            available=True,
            capabilities=["structured_planning"],
            detail="Deterministic Atlas planning is available without a model runtime.",
        )


class OllamaAtlasProvider:
    """Local provider metadata adapter; the first slice does not delegate tool choice to it."""

    def capabilities(self) -> AtlasModelProviderCapabilities:
        configured = os.environ.get("PRISM_AI_PROVIDER", "deterministic").lower() == "ollama"
        return AtlasModelProviderCapabilities(
            provider=AtlasModelProviderName.OLLAMA,
            available=configured,
            capabilities=["structured_planning", "local_inference", "streaming"] if configured else [],
            detail=(
                "Local Ollama is configured; Atlas still sends only compact metadata and validates every tool call."
                if configured
                else "Set PRISM_AI_PROVIDER=ollama to expose the optional server-side local provider."
            ),
        )


class AtlasProviderRegistry:
    def __init__(self) -> None:
        self._providers: tuple[AtlasModelProvider, ...] = (DeterministicAtlasProvider(), OllamaAtlasProvider())

    def capabilities(self) -> list[AtlasModelProviderCapabilities]:
        return [provider.capabilities() for provider in self._providers]

    def select(self) -> AtlasModelProviderName:
        requested = os.environ.get("PRISM_AI_PROVIDER", "deterministic").lower()
        if requested == AtlasModelProviderName.OLLAMA.value and self._providers[1].capabilities().available:
            return AtlasModelProviderName.OLLAMA
        return AtlasModelProviderName.DETERMINISTIC


class AtlasRunStore:
    """Append-only in-process runtime state; durable Atlas runs are a later Phase 10 gate."""

    def __init__(self) -> None:
        self._runs: dict[str, AtlasRunResponse] = {}
        self._cancelled: dict[str, threading.Event] = {}
        self._lock = threading.RLock()

    def create(self, request: AtlasRunRequest, provider: AtlasModelProviderName) -> AtlasRunResponse:
        run_id = f"atlas_{uuid.uuid4().hex}"
        plan = AtlasStructuredPlan(
            plan_id=f"plan_{uuid.uuid4().hex}", objective=request.objective, dataset_id=request.dataset_id,
            provider=provider, created_at=datetime.now(timezone.utc),
            steps=[
                AtlasPlanStep(step_id="profile", title="Profile the active dataset", kind=AtlasStepKind.PROFILE_DATASET, specialist=AtlasSpecialistId.SCOUT, tool_name="overview.profile"),
                AtlasPlanStep(step_id="methodology", title="Review statistical readiness", kind=AtlasStepKind.METHODOLOGY_REVIEW, specialist=AtlasSpecialistId.STAT, tool_name="atlas.methodology_review"),
                AtlasPlanStep(step_id="audit", title="Audit evidence and limits", kind=AtlasStepKind.AUDIT_EVIDENCE, specialist=AtlasSpecialistId.AUDITOR, tool_name="atlas.evidence_audit"),
            ],
        )
        result = AtlasRunResponse(run_id=run_id, plan=plan)
        with self._lock:
            self._runs[run_id] = result
            self._cancelled[run_id] = threading.Event()
        self.append_event(run_id, AtlasRunEventType.RUN_CREATED, payload={"dataset_id": request.dataset_id})
        self.append_event(run_id, AtlasRunEventType.PLAN_CREATED, payload={"plan_id": plan.plan_id, "provider": provider.value})
        return self.get(run_id)

    def get(self, run_id: str) -> AtlasRunResponse:
        with self._lock:
            current = self._runs.get(run_id)
            if current is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Atlas run was not found.")
            return current.model_copy(deep=True)

    def update(self, response: AtlasRunResponse) -> None:
        with self._lock:
            self._runs[response.run_id] = response.model_copy(deep=True)

    def cancelled(self, run_id: str) -> bool:
        with self._lock:
            marker = self._cancelled.get(run_id)
            return marker.is_set() if marker is not None else False

    def request_cancel(self, run_id: str) -> AtlasRunResponse:
        with self._lock:
            marker = self._cancelled.get(run_id)
            if marker is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Atlas run was not found.")
            marker.set()
        return self.get(run_id)

    def append_event(
        self, run_id: str, event_type: AtlasRunEventType, *, specialist: Optional[AtlasSpecialistId] = None,
        step_id: Optional[str] = None, payload: Optional[dict[str, object]] = None,
    ) -> None:
        with self._lock:
            current = self._runs[run_id]
            event = AtlasRunEvent(
                event_id=f"evt_{uuid.uuid4().hex}", run_id=run_id, sequence=len(current.events) + 1,
                type=event_type, occurred_at=datetime.now(timezone.utc), specialist=specialist,
                step_id=step_id, payload=payload or {},
            )
            self._runs[run_id] = current.model_copy(update={"events": [*current.events, event]})


providers = AtlasProviderRegistry()
runs = AtlasRunStore()


def _evidence(dataset_id: str, revision: int, fingerprint: str, summary: str) -> list[AtlasEvidenceReference]:
    return [
        AtlasEvidenceReference(
            evidence_id=f"dataset:{dataset_id}:r{revision}", kind="dataset_revision", summary="Active DatasetStore revision.",
            dataset_id=dataset_id, dataset_revision=revision, source_fingerprint=fingerprint,
        ),
        AtlasEvidenceReference(
            evidence_id=f"overview:{dataset_id}:r{revision}", kind="overview_profile", summary=summary,
            dataset_id=dataset_id, dataset_revision=revision, source_fingerprint=fingerprint,
        ),
    ]


def _replace_step(run: AtlasRunResponse, step_id: str, state: AtlasStepState, *, evidence: Optional[list[AtlasEvidenceReference]] = None, error: Optional[str] = None) -> AtlasRunResponse:
    steps = []
    for step in run.plan.steps:
        if step.step_id == step_id:
            steps.append(step.model_copy(update={"state": state, "attempts": step.attempts + 1 if state is AtlasStepState.RUNNING else step.attempts, "evidence": evidence if evidence is not None else step.evidence, "error": error}))
        else:
            steps.append(step)
    state_for_plan = AtlasPlanState.RUNNING if state is AtlasStepState.RUNNING else run.plan.state
    return run.model_copy(update={"plan": run.plan.model_copy(update={"steps": steps, "state": state_for_plan})})


def _complete_step(run_id: str, step_id: str, specialist: AtlasSpecialistId, evidence: list[AtlasEvidenceReference]) -> None:
    run = _replace_step(runs.get(run_id), step_id, AtlasStepState.COMPLETED, evidence=evidence)
    runs.update(run)
    runs.append_event(run_id, AtlasRunEventType.STEP_COMPLETED, specialist=specialist, step_id=step_id, payload={"evidence_ids": [item.evidence_id for item in evidence]})


def _cancel_run(run_id: str) -> None:
    run = runs.get(run_id)
    steps = [step.model_copy(update={"state": AtlasStepState.CANCELLED}) if step.state in {AtlasStepState.PENDING, AtlasStepState.RUNNING} else step for step in run.plan.steps]
    runs.update(run.model_copy(update={"plan": run.plan.model_copy(update={"state": AtlasPlanState.CANCELLED, "steps": steps})}))
    runs.append_event(run_id, AtlasRunEventType.RUN_CANCELLED, payload={"reason": "user_requested"})


def execute(run_id: str) -> None:
    """Execute only the three declared first-wave tools and record every transition."""
    try:
        for step in runs.get(run_id).plan.steps:
            if runs.cancelled(run_id):
                _cancel_run(run_id)
                return
            current = _replace_step(runs.get(run_id), step.step_id, AtlasStepState.RUNNING)
            runs.update(current)
            runs.append_event(run_id, AtlasRunEventType.STEP_STARTED, specialist=step.specialist, step_id=step.step_id, payload={"tool": step.tool_name})
            profile = get_profile(current.plan.dataset_id)
            evidence = _evidence(profile.dataset.dataset_id, profile.dataset.revision, profile.provenance.source_fingerprint, f"Overview profile: {profile.quality.n_rows:,} rows, {profile.quality.n_cols} columns, health {profile.health.total}/100.")
            if step.kind is AtlasStepKind.PROFILE_DATASET:
                conclusion = AtlasCouncilConclusion(specialist=AtlasSpecialistId.SCOUT, conclusion=f"Profiled {profile.dataset.source_name}: {profile.quality.n_rows:,} rows × {profile.quality.n_cols} columns; health score {profile.health.total}/100 and missingness {profile.quality.total_missing_pct:.2f}%.", confidence="high", evidence=evidence)
            elif step.kind is AtlasStepKind.METHODOLOGY_REVIEW:
                conclusion = AtlasCouncilConclusion(specialist=AtlasSpecialistId.STAT, conclusion="No inferential test was run because this request does not declare an outcome, hypothesis, comparison, or split strategy.", confidence="high", objections=["Do not infer causality, significance, or model performance from a profile alone."], evidence=evidence)
            else:
                conclusion = AtlasCouncilConclusion(specialist=AtlasSpecialistId.AUDITOR, conclusion="The current result is grounded in the active DatasetStore revision and deterministic Overview profile only.", confidence="high", objections=["No web research, raw-row provider transfer, SQL execution, Python execution, or model training occurred."], evidence=evidence)
            _complete_step(run_id, step.step_id, step.specialist, evidence)
            updated = runs.get(run_id)
            runs.update(updated.model_copy(update={"council": [*updated.council, conclusion], "evidence": [*updated.evidence, *[item for item in evidence if item not in updated.evidence]]}))
            runs.append_event(run_id, AtlasRunEventType.COUNCIL_CONCLUSION, specialist=step.specialist, step_id=step.step_id, payload={"confidence": conclusion.confidence, "objections": conclusion.objections})
        finished = runs.get(run_id)
        profile = get_profile(finished.plan.dataset_id)
        answer = f"Atlas completed a deterministic first-pass assessment of {profile.dataset.source_name}: {profile.quality.n_rows:,} rows × {profile.quality.n_cols} columns, health {profile.health.total}/100, and {profile.quality.total_missing_pct:.2f}% missing cells. The next safe step is to define a decision, outcome, and evaluation criteria before selecting a statistical or ML workflow."
        runs.update(finished.model_copy(update={"plan": finished.plan.model_copy(update={"state": AtlasPlanState.COMPLETED}), "answer": answer, "uncertainty": "This is a profile and methodology review, not a causal conclusion, statistical result, or trained model."}))
        runs.append_event(run_id, AtlasRunEventType.RUN_COMPLETED, specialist=AtlasSpecialistId.ATLAS, payload={"answer_grounded": True})
    except HTTPException as error:
        failed = runs.get(run_id)
        runs.update(failed.model_copy(update={"plan": failed.plan.model_copy(update={"state": AtlasPlanState.FAILED}), "uncertainty": str(error.detail)}))
        runs.append_event(run_id, AtlasRunEventType.RUN_FAILED, payload={"detail": str(error.detail)})


async def stream_events(run_id: str) -> AsyncIterator[str]:
    """Replay real stored events and continue until this bounded first-wave run reaches terminal state."""
    yielded = 0
    while True:
        run = runs.get(run_id)
        for event in run.events[yielded:]:
            yield ServerSentEvent(event="atlas.run", id=event.event_id, data=event.model_dump(mode="json")).encode()
            yielded += 1
        if run.plan.state in {AtlasPlanState.COMPLETED, AtlasPlanState.FAILED, AtlasPlanState.CANCELLED}:
            return
        await asyncio.sleep(0.02)


def cortex_graph(run_id: str) -> CortexGraphState:
    run = runs.get(run_id)
    nodes = [CortexNode(node_id=f"run:{run_id}", kind=CortexNodeKind.RUN, label="Atlas run", state=run.plan.state.value, source_id=run_id)]
    edges: list[CortexEdge] = []
    for step in run.plan.steps:
        step_node = f"step:{run_id}:{step.step_id}"
        specialist_node = f"specialist:{step.specialist.value}"
        nodes.extend([
            CortexNode(node_id=step_node, kind=CortexNodeKind.PLAN_STEP, label=step.title, state=step.state.value, source_id=step.step_id),
            CortexNode(node_id=specialist_node, kind=CortexNodeKind.SPECIALIST, label=step.specialist.value.title(), state="visible", source_id=step.specialist.value),
        ])
        edges.extend([
            CortexEdge(edge_id=f"contains:{step_node}", source_node_id=f"run:{run_id}", target_node_id=step_node, relation="contains"),
            CortexEdge(edge_id=f"executor:{step_node}", source_node_id=step_node, target_node_id=specialist_node, relation="executed_by"),
        ])
        for evidence in step.evidence:
            evidence_node = f"evidence:{step.step_id}:{evidence.evidence_id}"
            nodes.append(CortexNode(node_id=evidence_node, kind=CortexNodeKind.EVIDENCE, label=evidence.summary, state="recorded", source_id=evidence.evidence_id))
            edges.append(CortexEdge(edge_id=f"produced:{step_node}:{evidence.evidence_id}", source_node_id=step_node, target_node_id=evidence_node, relation="produced"))
    unique_nodes = {node.node_id: node for node in nodes}
    unique_edges = {edge.edge_id: edge for edge in edges}
    return CortexGraphState(run_id=run_id, nodes=list(unique_nodes.values()), edges=list(unique_edges.values()), generated_at=datetime.now(timezone.utc))
