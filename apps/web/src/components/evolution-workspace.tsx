"use client";

import { useEffect, useState } from "react";
import type {
  AtlasAdapterCapability,
  AtlasBenchCorpusSummary,
  AtlasCandidateArtifact,
  AtlasFoundryCapability,
  AtlasPreferenceDatasetVersion,
  AtlasProductionPointer,
  AtlasTrainingDatasetVersion,
  AtlasTrainingJob,
} from "@prism/api-contracts";
import { apiUrl } from "../config/api";

export function EvolutionWorkspace() {
  const [capability, setCapability] = useState<AtlasFoundryCapability | null>(null);
  const [corpus, setCorpus] = useState<AtlasBenchCorpusSummary | null>(null);
  const [current, setCurrent] = useState<AtlasProductionPointer | null>(null);
  const [history, setHistory] = useState<AtlasProductionPointer[]>([]);
  const [candidates, setCandidates] = useState<AtlasCandidateArtifact[]>([]);
  const [trainingDatasets, setTrainingDatasets] = useState<AtlasTrainingDatasetVersion[]>([]);
  const [preferenceDatasets, setPreferenceDatasets] = useState<AtlasPreferenceDatasetVersion[]>([]);
  const [jobs, setJobs] = useState<AtlasTrainingJob[]>([]);
  const [adapters, setAdapters] = useState<AtlasAdapterCapability[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      const [capabilityRes, corpusRes, currentRes, historyRes, candidatesRes, trainingRes, preferenceRes, jobsRes, adaptersRes] = await Promise.all([
        fetch(apiUrl("/api/v1/atlas/foundry/capability")),
        fetch(apiUrl("/api/v1/atlas/bench/corpus/summary")),
        fetch(apiUrl("/api/v1/atlas/promotion/current")),
        fetch(apiUrl("/api/v1/atlas/promotion/history")),
        fetch(apiUrl("/api/v1/atlas/foundry/candidates")),
        fetch(apiUrl("/api/v1/atlas/foundry/training-datasets")),
        fetch(apiUrl("/api/v1/atlas/foundry/preference-datasets")),
        fetch(apiUrl("/api/v1/atlas/foundry/jobs")),
        fetch(apiUrl("/api/v1/atlas/adapters/capabilities")),
      ]);
      if (capabilityRes.ok) setCapability((await capabilityRes.json()) as AtlasFoundryCapability);
      if (corpusRes.ok) setCorpus((await corpusRes.json()) as AtlasBenchCorpusSummary);
      if (currentRes.ok) setCurrent((await currentRes.json()) as AtlasProductionPointer | null);
      if (historyRes.ok) setHistory((await historyRes.json()) as AtlasProductionPointer[]);
      if (candidatesRes.ok) setCandidates((await candidatesRes.json()) as AtlasCandidateArtifact[]);
      if (trainingRes.ok) setTrainingDatasets((await trainingRes.json()) as AtlasTrainingDatasetVersion[]);
      if (preferenceRes.ok) setPreferenceDatasets((await preferenceRes.json()) as AtlasPreferenceDatasetVersion[]);
      if (jobsRes.ok) setJobs((await jobsRes.json()) as AtlasTrainingJob[]);
      if (adaptersRes.ok) setAdapters((await adaptersRes.json()) as AtlasAdapterCapability[]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Atlas Evolution data failed to load.");
    }
  }
  useEffect(() => { void refresh(); }, []);

  async function withBusy(action: () => Promise<Response>) {
    setBusy(true); setError(null);
    try {
      const response = await action();
      if (!response.ok) { setError(((await response.json()) as { detail?: string }).detail ?? "The action failed."); return; }
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The action failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="evolution-workspace">
      <header className="atlas-heading">
        <div>
          <span className="eyebrow">ATLAS · EVOLUTION</span>
          <h1>Self-improvement, proven before it ships.</h1>
          <p>Soup trains, AtlasBench judges, Shadow Brain compares -- and no candidate earns production merely because its training loss went down. Everything below is real, durable state; an empty panel means nothing has happened yet, not that the feature is missing.</p>
        </div>
        {capability ? <span className={`migration-chip ${capability.can_train ? "ready" : "unavailable"}`} title={capability.detail}>{capability.backend} · {capability.can_train ? "ready" : "unavailable"}</span> : null}
      </header>
      {error ? <p className="query-error" role="alert">{error}</p> : null}

      <section className="evolution-grid">
        <ProductionPanel
          current={current}
          canRollback={history.length > 1}
          busy={busy}
          onRollback={() => {
            const reason = window.prompt("Reason for rollback (kept in the audit trail):");
            if (reason) void withBusy(() => fetch(apiUrl(`/api/v1/atlas/promotion/rollback?${new URLSearchParams({ reason }).toString()}`), { method: "POST" }));
          }}
        />
        <CandidatePanel candidates={candidates} />
        <CorpusPanel corpus={corpus} />
      </section>

      <section className="evolution-grid">
        <DatasetPanel
          title="Training datasets (SFT)"
          note="Built from verified, completed Atlas runs -- never fabricated interactions."
          versions={trainingDatasets.map((version) => ({ id: version.version_id, createdAt: version.created_at, examples: version.train_count + version.validation_count + version.test_count, source: version.source_run_count, excluded: version.excluded_count }))}
          busy={busy}
          onBuild={() => void withBusy(() => fetch(apiUrl("/api/v1/atlas/foundry/training-datasets"), { method: "POST" }))}
        />
        <DatasetPanel
          title="Preference datasets (DPO)"
          note="Built from real Atlas-memory corrections (supersede()) -- never a manufactured rejected answer."
          versions={preferenceDatasets.map((version) => ({ id: version.version_id, createdAt: version.created_at, examples: version.train_count + version.validation_count + version.test_count, source: version.source_count, excluded: version.excluded_count }))}
          busy={busy}
          onBuild={() => void withBusy(() => fetch(apiUrl("/api/v1/atlas/foundry/preference-datasets"), { method: "POST" }))}
        />
        <JobsPanel jobs={jobs} busy={busy} onReconcile={() => void withBusy(() => fetch(apiUrl("/api/v1/atlas/foundry/jobs:reconcile"), { method: "POST" }))} />
      </section>

      <PromotionHistoryPanel history={history} />
      <AdapterPanel adapters={adapters} />
    </article>
  );
}

function ProductionPanel({ current, canRollback, busy, onRollback }: { current: AtlasProductionPointer | null; canRollback: boolean; busy: boolean; onRollback: () => void }) {
  return (
    <aside className="atlas-council evolution-panel">
      <span className="eyebrow">PRODUCTION</span>
      {current ? (
        <>
          <strong>{current.candidate_id}</strong>
          <small>Promoted {new Date(current.promoted_at).toLocaleString()}{current.is_rollback ? " · via rollback" : ""}</small>
          <p>{current.reason}</p>
          <button className="secondary" disabled={!canRollback || busy} onClick={onRollback}>Roll back to previous candidate</button>
        </>
      ) : (
        <p>No candidate has ever been promoted. Production Atlas is running its base deterministic/Ollama provider -- there is no fabricated "current model" to display.</p>
      )}
    </aside>
  );
}

function CandidatePanel({ candidates }: { candidates: AtlasCandidateArtifact[] }) {
  return (
    <aside className="atlas-specialists evolution-panel">
      <span className="eyebrow">CANDIDATES</span>
      {candidates.length ? candidates.slice(0, 6).map((candidate) => (
        <div key={candidate.candidate_id}>
          <strong>{candidate.candidate_id}</strong>
          <small>{candidate.base_model} · {candidate.method}</small>
        </div>
      )) : <p>No candidate has completed training yet. A candidate is registered here only once a Foundry job actually produces adapter output on disk.</p>}
    </aside>
  );
}

function CorpusPanel({ corpus }: { corpus: AtlasBenchCorpusSummary | null }) {
  return (
    <aside className="atlas-council evolution-panel">
      <span className="eyebrow">ATLASBENCH CORPUS</span>
      {corpus ? (
        <>
          <strong>{corpus.total_tasks} tasks · {corpus.corpus_version}</strong>
          <ul className="evolution-category-list">
            {(corpus.category_counts ?? []).map((entry) => <li key={entry.category}><span>{entry.category.replaceAll("_", " ")}</span><span>{entry.task_count}</span></li>)}
          </ul>
        </>
      ) : <p>Corpus summary is unavailable.</p>}
    </aside>
  );
}

interface DatasetVersionRow { id: string; createdAt: string; examples: number; source: number; excluded: number; }

function DatasetPanel({ title, note, versions, busy, onBuild }: { title: string; note: string; versions: DatasetVersionRow[]; busy: boolean; onBuild: () => void }) {
  return (
    <section className="atlas-plan evolution-panel">
      <span className="eyebrow">{title}</span>
      <p className="evolution-note">{note}</p>
      <button disabled={busy} onClick={onBuild}>Build from current history</button>
      {versions.length ? (
        <ol className="evolution-version-list">
          {versions.slice(0, 5).map((version) => (
            <li key={version.id}>
              <code>{version.id}</code>
              <small>{version.examples} examples · {version.source} source records · {version.excluded} excluded · {new Date(version.createdAt).toLocaleString()}</small>
            </li>
          ))}
        </ol>
      ) : <p>No version has been built yet.</p>}
    </section>
  );
}

function JobsPanel({ jobs, busy, onReconcile }: { jobs: AtlasTrainingJob[]; busy: boolean; onReconcile: () => void }) {
  return (
    <aside className="atlas-specialists evolution-panel">
      <span className="eyebrow">TRAINING JOBS</span>
      <button className="secondary" disabled={busy} onClick={onReconcile}>Advance queued/running jobs</button>
      {jobs.length ? jobs.map((job) => (
        <div key={job.job_id}>
          <span className={`specialist-signal ${job.state}`} />
          <strong>{job.job_id.slice(-8)}</strong>
          <small>{job.backend} · {job.state}{job.error ? ` · ${job.error}` : ""}</small>
        </div>
      )) : <p>No training job is queued or running. Foundry training is admitted through the Resource Governor and never starts unmanaged.</p>}
    </aside>
  );
}

function PromotionHistoryPanel({ history }: { history: AtlasProductionPointer[] }) {
  return (
    <section className="atlas-command evolution-history">
      <span className="eyebrow">PROMOTION &amp; ROLLBACK HISTORY</span>
      {history.length ? (
        <ol className="evolution-timeline">
          {history.map((event) => (
            <li key={event.event_id} data-rollback={event.is_rollback}>
              <strong>{event.candidate_id}</strong>
              <small>{new Date(event.promoted_at).toLocaleString()}{event.previous_candidate_id ? ` · replaced ${event.previous_candidate_id}` : " · first production candidate"}{event.is_rollback ? " · ROLLBACK" : ""}</small>
              <p>{event.reason}</p>
            </li>
          ))}
        </ol>
      ) : <p>No promotion or rollback has ever occurred. This history is append-only: nothing is ever overwritten once it happens.</p>}
    </section>
  );
}

function AdapterPanel({ adapters }: { adapters: AtlasAdapterCapability[] }) {
  return (
    <section className="atlas-command evolution-history">
      <span className="eyebrow">LOGICAL ADAPTERS</span>
      {adapters.length ? (
        <ul className="evolution-category-list">
          {adapters.map((adapter) => <li key={adapter.adapter}><span>{adapter.adapter}</span><span className={`migration-chip ${adapter.can_hot_swap ? "ready" : "legacy"}`}>{adapter.can_hot_swap ? "hot-swap ready" : "core fallback only"}</span></li>)}
        </ul>
      ) : <p>Adapter capability is unavailable.</p>}
    </section>
  );
}
