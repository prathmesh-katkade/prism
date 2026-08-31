"use client";

import React, { useCallback, useEffect, useState } from "react";
import { apiUrl } from "../config/api";
import { Icon, type IconName } from "./icons";

/** Phase 8E: the evidence/lineage inspector - the read-only backend intelligence from
 * Phase 8A-8D (provenance, direct parent/child links, freshness) made visible in the
 * product. Purely a viewer: it never mutates the analytical object it describes, and
 * inspecting old (stale/superseded) evidence works exactly like inspecting current
 * evidence - the object is immutable either way. Rerun (Phase 8F) is a separate,
 * explicit action layered on top, not implied by simply viewing this panel. */

interface DatasetRefShape {
  dataset_id: string;
  revision: number;
  source_fingerprint: string;
}

interface ReproducibilityShape {
  kind: string;
  producer: { service: string; version: string };
  operation?: string;
  test?: string;
  columns?: string[];
  parameters: Record<string, unknown>;
}

export interface AnalyticalObjectShape {
  object_id: string;
  kind: string;
  lifecycle: string;
  schema_version: string;
  payload: Record<string, unknown>;
  provenance: {
    dataset: DatasetRefShape;
    parent_refs: { object_id: string; relation: string }[];
    warnings: string[];
    evidence_refs: { evidence_id: string; kind: string; summary?: string | null }[];
    reproducibility: ReproducibilityShape;
    created_at: string;
  };
}

export interface FreshnessShape {
  state: "current" | "stale" | "superseded" | "unknown" | "invalid";
  freshness_known: boolean;
  active_revision: number | null;
  active_fingerprint: string | null;
  reason: string;
  reason_code: string;
}

type ReproductionMode = "same_revision" | "current_revision";

interface ReproductionResponseShape {
  outcome: "created" | "unsupported" | "validation_failed" | "source_revision_unavailable";
  original_object_id: string;
  mode: ReproductionMode;
  new_object: AnalyticalObjectShape | null;
  detail: string;
}

const OUTCOME_LABEL: Record<ReproductionResponseShape["outcome"], string> = {
  created: "New object created",
  unsupported: "Rerun not supported for this object",
  validation_failed: "Could not reproduce",
  source_revision_unavailable: "Original data unavailable",
};

type AtlasLineageAction = "explain_provenance" | "explain_staleness" | "explain_lineage" | "recommend_reruns" | "explain_evidence";

const ATLAS_LINEAGE_ACTIONS: readonly { action: AtlasLineageAction; label: string }[] = [
  { action: "explain_provenance", label: "What produced this?" },
  { action: "explain_staleness", label: "Why is this stale?" },
  { action: "explain_lineage", label: "Explain its lineage" },
  { action: "recommend_reruns", label: "What should I rerun?" },
  { action: "explain_evidence", label: "Explain its evidence" },
];

interface AtlasLineageResponseShape {
  action: AtlasLineageAction | "compare_versions";
  summary: string;
  uncertainty: string;
  evidence: { label: string; value: string }[];
  limitation: string | null;
}

const KIND_LABEL: Record<string, string> = {
  dataset_revision: "Dataset revision",
  profile: "Profile",
  query_result: "SQL result",
  cleaning_plan: "Clean transformation",
  visualization: "Visualization",
  analysis: "Statistical analysis",
  forecast: "Forecast",
  ml_model: "ML result",
  evidence: "AI Analyst evidence",
};

const FRESHNESS_LABEL: Record<FreshnessShape["state"], string> = {
  current: "Current",
  stale: "Stale",
  superseded: "Superseded",
  unknown: "Freshness unknown",
  invalid: "Invalid",
};

const FRESHNESS_ICON: Record<FreshnessShape["state"], IconName> = {
  current: "check",
  stale: "clock",
  superseded: "layers",
  unknown: "help",
  invalid: "alert",
};

interface LoadedState {
  object: AnalyticalObjectShape;
  freshness: FreshnessShape | null;
  parents: AnalyticalObjectShape[];
  children: AnalyticalObjectShape[];
}

async function fetchJson<T>(path: string): Promise<T | null> {
  const response = await fetch(apiUrl(path));
  if (!response.ok) return null;
  return (await response.json()) as T;
}

export function EvidenceInspector({ objectId, onClose }: { objectId: string; onClose(): void }) {
  const [activeId, setActiveId] = useState(objectId);
  const [history, setHistory] = useState<string[]>([]);
  const [loaded, setLoaded] = useState<LoadedState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setActiveId(objectId);
    setHistory([]);
  }, [objectId]);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    setError(null);
    const object = await fetchJson<AnalyticalObjectShape>(`/api/v1/lineage/objects/${id}`);
    if (!object) {
      setError("This analytical object could not be found.");
      setLoaded(null);
      setLoading(false);
      return;
    }
    const [freshness, parents, children] = await Promise.all([
      fetchJson<FreshnessShape>(`/api/v1/lineage/objects/${id}/freshness`),
      fetchJson<AnalyticalObjectShape[]>(`/api/v1/lineage/objects/${id}/parents`),
      fetchJson<AnalyticalObjectShape[]>(`/api/v1/lineage/objects/${id}/children`),
    ]);
    setLoaded({ object, freshness, parents: parents ?? [], children: children ?? [] });
    setLoading(false);
  }, []);

  useEffect(() => {
    void load(activeId);
  }, [activeId, load]);

  const navigateTo = useCallback((id: string) => {
    setHistory((previous) => [...previous, activeId]);
    setActiveId(id);
  }, [activeId]);

  const goBack = useCallback(() => {
    setHistory((previous) => {
      if (previous.length === 0) return previous;
      const next = [...previous];
      const last = next.pop() as string;
      setActiveId(last);
      return next;
    });
  }, []);

  return (
    <aside className="inspector evidence-inspector" aria-label="Evidence inspector">
      <div className="inspector-heading">
        <div>
          <span className="eyebrow">EVIDENCE</span>
          <h2>{loaded ? KIND_LABEL[loaded.object.kind] ?? loaded.object.kind : "Evidence"}</h2>
        </div>
        <button className="icon-button" onClick={onClose} aria-label="Hide inspector">
          <Icon name="close" />
        </button>
      </div>
      {history.length > 0 ? (
        <button className="evidence-back" onClick={goBack}>
          <Icon name="arrow" className="icon-back" /> Back
        </button>
      ) : null}
      {loading ? <p className="quiet-note" role="status">Loading evidence…</p> : null}
      {error ? <p className="quiet-note" role="alert">{error}</p> : null}
      {!loading && !error && loaded ? <EvidenceBody state={loaded} onNavigate={navigateTo} /> : null}
    </aside>
  );
}

function EvidenceBody({ state, onNavigate }: { state: LoadedState; onNavigate(id: string): void }) {
  const { object, freshness, parents, children } = state;
  const parameters = Object.entries(object.provenance.reproducibility.parameters ?? {});
  return (
    <>
      {freshness ? <FreshnessBadge freshness={freshness} /> : null}
      <dl className="inspector-data evidence-identity">
        <div><dt>Object ID</dt><dd><code>{object.object_id}</code></dd></div>
        <div><dt>Kind</dt><dd>{KIND_LABEL[object.kind] ?? object.kind}</dd></div>
        <div><dt>Lifecycle</dt><dd>{object.lifecycle}</dd></div>
        <div><dt>Dataset revision</dt><dd>{object.provenance.dataset.dataset_id} · rev {object.provenance.dataset.revision}</dd></div>
        <div><dt>Source fingerprint</dt><dd><code>{object.provenance.dataset.source_fingerprint.slice(0, 12)}…</code></dd></div>
        <div><dt>Producer</dt><dd>{object.provenance.reproducibility.producer.service} v{object.provenance.reproducibility.producer.version}</dd></div>
        <div><dt>Method</dt><dd>{object.provenance.reproducibility.operation ?? object.provenance.reproducibility.test ?? "—"}</dd></div>
        <div><dt>Created</dt><dd>{new Date(object.provenance.created_at).toLocaleString()}</dd></div>
      </dl>
      {parameters.length > 0 ? (
        <section className="evidence-section">
          <span className="eyebrow">PARAMETERS</span>
          <dl className="inspector-data">
            {parameters.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{formatParam(value)}</dd></div>)}
          </dl>
        </section>
      ) : null}
      {object.provenance.warnings.length > 0 ? (
        <section className="evidence-section">
          <span className="eyebrow">WARNINGS</span>
          <ul className="evidence-list">{object.provenance.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul>
        </section>
      ) : null}
      {object.provenance.evidence_refs.length > 0 ? (
        <section className="evidence-section">
          <span className="eyebrow">EVIDENCE</span>
          <ul className="evidence-list">{object.provenance.evidence_refs.map((ref) => <li key={ref.evidence_id}>{ref.summary ?? ref.kind}</li>)}</ul>
        </section>
      ) : null}
      <section className="evidence-section">
        <span className="eyebrow">UPSTREAM DEPENDENCIES</span>
        {parents.length ? (
          <ul className="evidence-lineage-list">
            {parents.map((parent) => (
              <li key={parent.object_id}>
                <button onClick={() => onNavigate(parent.object_id)}>
                  <Icon name="link" /> {KIND_LABEL[parent.kind] ?? parent.kind}
                </button>
              </li>
            ))}
          </ul>
        ) : <p className="quiet-note">No upstream dependency recorded — this is a root object.</p>}
      </section>
      <section className="evidence-section">
        <span className="eyebrow">DOWNSTREAM DEPENDENTS</span>
        {children.length ? (
          <ul className="evidence-lineage-list">
            {children.map((child) => (
              <li key={child.object_id}>
                <button onClick={() => onNavigate(child.object_id)}>
                  <Icon name="link" /> {KIND_LABEL[child.kind] ?? child.kind}
                </button>
              </li>
            ))}
          </ul>
        ) : <p className="quiet-note">Nothing recorded depends on this object yet.</p>}
      </section>
      <ReproducibilitySection object={object} onNavigate={onNavigate} />
      <AtlasLineageSection objectId={object.object_id} />
    </>
  );
}

function AtlasLineageSection({ objectId }: { objectId: string }) {
  const [pending, setPending] = useState<AtlasLineageAction | null>(null);
  const [result, setResult] = useState<AtlasLineageResponseShape | null>(null);

  async function ask(action: AtlasLineageAction) {
    setPending(action);
    setResult(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/lineage/objects/${objectId}/atlas`), {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action }),
      });
      setResult(await response.json() as AtlasLineageResponseShape);
    } catch {
      setResult({ action, summary: "Atlas could not be reached.", uncertainty: "", evidence: [], limitation: "The request failed." });
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="evidence-section">
      <span className="eyebrow">ATLAS · LINEAGE-AWARE</span>
      <div className="atlas-action-row">
        {ATLAS_LINEAGE_ACTIONS.map(({ action, label }) => (
          <button key={action} disabled={pending !== null} onClick={() => void ask(action)}>
            {pending === action ? "Asking…" : label}
          </button>
        ))}
      </div>
      {result ? (
        <aside className="atlas-result" aria-live="polite">
          <span className="eyebrow">ATLAS · {result.action.replaceAll("_", " ")}</span>
          <strong>{result.summary}</strong>
          {result.limitation ? <small role="alert">{result.limitation}</small> : null}
          {result.uncertainty ? <small>{result.uncertainty}</small> : null}
          {result.evidence.length ? (
            <dl className="inspector-data">
              {result.evidence.map((item, index) => <div key={index}><dt>{item.label}</dt><dd>{item.value}</dd></div>)}
            </dl>
          ) : null}
        </aside>
      ) : null}
    </section>
  );
}

function ReproducibilitySection({ object, onNavigate }: { object: AnalyticalObjectShape; onNavigate(id: string): void }) {
  const [pending, setPending] = useState<ReproductionMode | null>(null);
  const [result, setResult] = useState<ReproductionResponseShape | null>(null);

  async function rerun(mode: ReproductionMode) {
    setPending(mode);
    setResult(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/lineage/objects/${object.object_id}/rerun`), {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ mode }),
      });
      setResult(await response.json() as ReproductionResponseShape);
    } catch {
      setResult({ outcome: "validation_failed", original_object_id: object.object_id, mode, new_object: null, detail: "The rerun request could not be sent." });
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="evidence-section">
      <span className="eyebrow">REPRODUCIBILITY</span>
      <p className="quiet-note">
        {object.provenance.reproducibility.kind} reproducibility spec recorded — original revision{" "}
        {object.provenance.dataset.revision} of {object.provenance.dataset.dataset_id}. Reproducing never
        changes this object; it always creates a new one.
      </p>
      <div className="inspector-actions">
        <button disabled={pending !== null} onClick={() => void rerun("same_revision")}>
          {pending === "same_revision" ? "Reproducing…" : "Reproduce on original revision"}
        </button>
        <button disabled={pending !== null} onClick={() => void rerun("current_revision")}>
          {pending === "current_revision" ? "Rerunning…" : "Rerun on current data"}
        </button>
      </div>
      {result ? <ReproductionOutcome result={result} onNavigate={onNavigate} /> : null}
    </section>
  );
}

function ReproductionOutcome({ result, onNavigate }: { result: ReproductionResponseShape; onNavigate(id: string): void }) {
  if (result.outcome === "created" && result.new_object) {
    return (
      <aside className="reproduction-outcome reproduction-created" aria-live="polite">
        <strong>{OUTCOME_LABEL[result.outcome]}</strong>
        <p>{result.detail}</p>
        <button onClick={() => onNavigate((result.new_object as AnalyticalObjectShape).object_id)}>View new result</button>
      </aside>
    );
  }
  return (
    <aside className="reproduction-outcome reproduction-blocked" role="alert">
      <strong>{OUTCOME_LABEL[result.outcome]}</strong>
      <p>{result.detail}</p>
    </aside>
  );
}

function FreshnessBadge({ freshness }: { freshness: FreshnessShape }) {
  return (
    <div className={`freshness-badge freshness-${freshness.state}`} role="status">
      <span className="freshness-badge-label">
        <Icon name={FRESHNESS_ICON[freshness.state]} />
        {FRESHNESS_LABEL[freshness.state]}
      </span>
      <p className="freshness-reason">{freshness.reason}</p>
    </div>
  );
}

function formatParam(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
