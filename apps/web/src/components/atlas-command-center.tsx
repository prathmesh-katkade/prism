"use client";

import { useEffect, useState } from "react";
import type {
  AtlasBaseModelVerification,
  AtlasBenchSuiteRun,
  AtlasCombinedSftDatasetVersion,
  AtlasCombinedTrainingSourceSummary,
  AtlasEmbeddingCapability,
  AtlasFeedbackEvent,
  AtlasMemoryRecord,
  AtlasOperationalScenarioResult,
  AtlasOperationalSuiteRun,
  AtlasProductionPointer,
  AtlasProductionTrustStatus,
  AtlasRunResponse,
  AtlasSpecialistIdentity,
  AtlasSyntheticTeacherManifest,
  AtlasSystemSeedManifest,
  AtlasVerifiedBaseModelCandidate,
} from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import { EvidencePanel, FeedbackItem, groupMemoriesByClass, MEMORY_CLASS_LABELS, MemoryRecordItem, PipelineStepper, RunMemoryTrace, SpecialistActivity, ToolTimeline, GuardrailPanel as RunGuardrailPanel } from "./atlas-run-activity";

type CorpusState = {
  systemSeed: AtlasSystemSeedManifest | null;
  syntheticTeacher: AtlasSyntheticTeacherManifest | null;
  combinedSft: AtlasCombinedSftDatasetVersion | null;
  summary: AtlasCombinedTrainingSourceSummary | null;
};

const emptyCorpus: CorpusState = { systemSeed: null, syntheticTeacher: null, combinedSft: null, summary: null };

/**
 * ATLAS First Light Command Center: the system-wide status screen above the
 * per-dataset AtlasWorkspace below it. Every number here comes from an
 * existing, already-tested backend route -- current-status, the base-model
 * trust routes, a bench run detail, the operational-cert run detail, and
 * the Foundry corpus list routes. Nothing here decides or verifies anything
 * new, and nothing is hardcoded: if production is still the legacy pointer,
 * this honestly says so instead of claiming Qwen is production.
 */
export function AtlasCommandCenter() {
  const [status, setStatus] = useState<AtlasProductionTrustStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [candidate, setCandidate] = useState<AtlasVerifiedBaseModelCandidate | null>(null);
  const [verification, setVerification] = useState<AtlasBaseModelVerification | null>(null);
  const [v1Run, setV1Run] = useState<AtlasBenchSuiteRun | null>(null);
  const [opcertRun, setOpcertRun] = useState<AtlasOperationalSuiteRun | null>(null);
  const [corpus, setCorpus] = useState<CorpusState>(emptyCorpus);
  const [benchByCandidate, setBenchByCandidate] = useState<AtlasBenchSuiteRun[]>([]);
  const [promotionHistory, setPromotionHistory] = useState<AtlasProductionPointer[]>([]);
  const [roster, setRoster] = useState<AtlasSpecialistIdentity[]>([]);
  const [recentRuns, setRecentRuns] = useState<AtlasRunResponse[]>([]);
  const [recentRunsFailed, setRecentRunsFailed] = useState(false);
  const [runFeedbackByRun, setRunFeedbackByRun] = useState<Record<string, AtlasFeedbackEvent[]>>({});
  const [systemMemories, setSystemMemories] = useState<AtlasMemoryRecord[]>([]);
  const [recentFeedback, setRecentFeedback] = useState<AtlasFeedbackEvent[]>([]);
  const [ragCapability, setRagCapability] = useState<AtlasEmbeddingCapability | null>(null);
  const [memoryFailed, setMemoryFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadStatus() {
      try {
        const response = await fetch(apiUrl("/api/v1/atlas/promotion/current-status"));
        if (!response.ok) throw new Error(String(response.status));
        const body = (await response.json()) as AtlasProductionTrustStatus;
        if (cancelled) return;
        setStatus(body);

        const candidateId = body.production?.candidate_id;
        if (body.candidate_kind === "verified_base_model" && candidateId) {
          const [candidateResponse, verificationResponse] = await Promise.all([
            fetch(apiUrl(`/api/v1/atlas/base-model-candidates/${candidateId}`)),
            fetch(apiUrl(`/api/v1/atlas/base-model-candidates/${candidateId}/verification`)),
          ]);
          if (!cancelled && candidateResponse.ok) setCandidate((await candidateResponse.json()) as AtlasVerifiedBaseModelCandidate);
          if (!cancelled && verificationResponse.ok) {
            const history = (await verificationResponse.json()) as AtlasBaseModelVerification[];
            setVerification(history[0] ?? null);
          }
        }

        if (body.latest_v1_run_id) {
          const runResponse = await fetch(apiUrl(`/api/v1/atlas/bench/runs/detail/${body.latest_v1_run_id}`));
          if (!cancelled && runResponse.ok) setV1Run((await runResponse.json()) as AtlasBenchSuiteRun);
        }

        if (body.latest_operational_cert_run_id) {
          const opcertResponse = await fetch(apiUrl(`/api/v1/atlas/operational-cert/runs/${body.latest_operational_cert_run_id}`));
          if (!cancelled && opcertResponse.ok) setOpcertRun((await opcertResponse.json()) as AtlasOperationalSuiteRun);
        }

        // Every recorded bench run for the current production candidate,
        // any corpus -- this is the whole AtlasBench V2 discovery path: no
        // run id or candidate id is ever hardcoded into this component.
        if (candidateId) {
          const benchResponse = await fetch(apiUrl(`/api/v1/atlas/bench/runs-by-candidate/${candidateId}`));
          if (!cancelled && benchResponse.ok) setBenchByCandidate((await benchResponse.json()) as AtlasBenchSuiteRun[]);
        }
      } catch {
        if (!cancelled) setStatusFailed(true);
      }
    }

    async function loadCorpus() {
      const [seedResponse, teacherResponse, sftResponse, summaryResponse] = await Promise.all([
        fetch(apiUrl("/api/v1/atlas/foundry/system-seed")).catch(() => null),
        fetch(apiUrl("/api/v1/atlas/foundry/synthetic-teacher")).catch(() => null),
        fetch(apiUrl("/api/v1/atlas/foundry/combined-sft-datasets")).catch(() => null),
        fetch(apiUrl("/api/v1/atlas/foundry/training-datasets:combined-summary")).catch(() => null),
      ]);
      if (cancelled) return;
      const seed = seedResponse?.ok ? ((await seedResponse.json()) as AtlasSystemSeedManifest[]) : [];
      const teacher = teacherResponse?.ok ? ((await teacherResponse.json()) as AtlasSyntheticTeacherManifest[]) : [];
      const sft = sftResponse?.ok ? ((await sftResponse.json()) as AtlasCombinedSftDatasetVersion[]) : [];
      const summary = summaryResponse?.ok ? ((await summaryResponse.json()) as AtlasCombinedTrainingSourceSummary) : null;
      if (!cancelled) setCorpus({ systemSeed: seed[0] ?? null, syntheticTeacher: teacher[0] ?? null, combinedSft: sft[0] ?? null, summary });
    }

    async function loadTrustHistory() {
      const response = await fetch(apiUrl("/api/v1/atlas/promotion/history")).catch(() => null);
      if (!cancelled && response?.ok) setPromotionHistory((await response.json()) as AtlasProductionPointer[]);
    }

    async function loadActivity() {
      const rosterResponse = await fetch(apiUrl("/api/v1/atlas/specialists")).catch(() => null);
      if (!cancelled && rosterResponse?.ok) setRoster((await rosterResponse.json()) as AtlasSpecialistIdentity[]);

      try {
        const idsResponse = await fetch(apiUrl("/api/v1/atlas/runs?limit=8"));
        if (!idsResponse.ok) throw new Error(String(idsResponse.status));
        const ids = (await idsResponse.json()) as string[];
        const runs = await Promise.all(
          ids.map((id) => fetch(apiUrl(`/api/v1/atlas/runs/${id}`)).then((response) => (response.ok ? (response.json() as Promise<AtlasRunResponse>) : null)))
        );
        const realRuns = runs.filter((item): item is AtlasRunResponse => item !== null);
        if (!cancelled) setRecentRuns(realRuns);

        // Real per-run corrections via the dedicated GET /feedback/runs/{id}
        // route (an exact match) -- fetched alongside each recent run's own
        // detail so the run browser's expanded view can show them without a
        // second round trip per expansion.
        const feedbackEntries = await Promise.all(
          realRuns.map((run) => fetch(apiUrl(`/api/v1/atlas/feedback/runs/${run.run_id}`)).then((response) => (response.ok ? (response.json() as Promise<AtlasFeedbackEvent[]>) : [])).then((events) => [run.run_id, events] as const))
        );
        if (!cancelled) setRunFeedbackByRun(Object.fromEntries(feedbackEntries));
      } catch {
        if (!cancelled) setRecentRunsFailed(true);
      }
    }

    async function loadMemory() {
      try {
        const [memoryResponse, feedbackResponse, ragResponse] = await Promise.all([
          fetch(apiUrl("/api/v1/atlas/memories?limit=50")),
          fetch(apiUrl("/api/v1/atlas/feedback/recent?limit=20")),
          fetch(apiUrl("/api/v1/atlas/retrieval/capability")),
        ]);
        if (cancelled) return;
        if (memoryResponse.ok) setSystemMemories((await memoryResponse.json()) as AtlasMemoryRecord[]);
        if (feedbackResponse.ok) setRecentFeedback((await feedbackResponse.json()) as AtlasFeedbackEvent[]);
        if (ragResponse.ok) setRagCapability((await ragResponse.json()) as AtlasEmbeddingCapability);
      } catch {
        if (!cancelled) setMemoryFailed(true);
      }
    }

    void loadStatus();
    void loadCorpus();
    void loadTrustHistory();
    void loadActivity();
    void loadMemory();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="atlas-command-center" aria-label="Atlas command center">
      <Hero status={status} failed={statusFailed} />
      <div className="acc-grid">
        <SystemCortexPanel status={status} candidate={candidate} verification={verification} v1Run={v1Run} opcertRun={opcertRun} corpus={corpus} />
        <RunActivityPanel runs={recentRuns} failed={recentRunsFailed} roster={roster} memories={systemMemories} feedbackByRun={runFeedbackByRun} />
        <TrustPanel status={status} candidate={candidate} verification={verification} history={promotionHistory} benchRuns={benchByCandidate} />
        <BenchPanel status={status} run={v1Run} candidateRuns={benchByCandidate} />
        <OperationalCertPanel status={status} run={opcertRun} />
        <CorpusPanel corpus={corpus} />
        <SystemMemoryPanel memories={systemMemories} feedback={recentFeedback} rag={ragCapability} failed={memoryFailed} />
      </div>
    </section>
  );
}

function Hero({ status, failed }: { status: AtlasProductionTrustStatus | null; failed: boolean }) {
  if (failed) {
    return (
      <header className="acc-hero acc-tone-unavailable">
        <span className="eyebrow">ATLAS</span>
        <h1>STATUS UNKNOWN</h1>
        <p>Could not reach the Atlas promotion status endpoint.</p>
      </header>
    );
  }
  if (!status) {
    return (
      <header className="acc-hero">
        <span className="eyebrow">ATLAS</span>
        <h1>Checking…</h1>
      </header>
    );
  }
  if (!status.production) {
    return (
      <header className="acc-hero acc-tone-unavailable">
        <span className="eyebrow">ATLAS</span>
        <h1>NO PRODUCTION MODEL</h1>
        <p>No candidate has ever been promoted to production.</p>
      </header>
    );
  }
  const verified = status.candidate_kind && status.trust_verification_state === "verified";
  const tone = verified ? "acc-tone-native" : status.candidate_kind ? "acc-tone-bridged" : "acc-tone-legacy";
  const roleLabel = verified ? "VERIFIED" : status.candidate_kind ? "CERTIFICATION PENDING" : "LEGACY";
  return (
    <header className={`acc-hero ${tone}`}>
      <span className="eyebrow">ATLAS · ONLINE</span>
      <h1>{status.runtime_model ?? "Unknown runtime model"}</h1>
      <p className="acc-hero-chips">
        <span>LOCAL</span>
        <span aria-hidden="true">·</span>
        <span>{roleLabel}</span>
        <span aria-hidden="true">·</span>
        <span>PRODUCTION</span>
      </p>
    </header>
  );
}

/**
 * The system-level counterpart to the per-run Cortex inside AtlasWorkspace
 * below: a lineage view built entirely from entities this component already
 * fetched for the other panels. Edges are only drawn where the backend
 * itself records the relationship (a candidate_id shared between the
 * production pointer, a bench run and an operational-cert run; a
 * seed_version/synthetic_teacher_version a combined SFT release actually
 * references) -- never a relationship this component is only guessing at.
 */
function SystemCortexPanel({
  status,
  candidate,
  verification,
  v1Run,
  opcertRun,
  corpus,
}: {
  status: AtlasProductionTrustStatus | null;
  candidate: AtlasVerifiedBaseModelCandidate | null;
  verification: AtlasBaseModelVerification | null;
  v1Run: AtlasBenchSuiteRun | null;
  opcertRun: AtlasOperationalSuiteRun | null;
  corpus: CorpusState;
}) {
  if (!status?.production) {
    return (
      <article className="acc-panel acc-panel-wide">
        <h2>System Cortex</h2>
        <p className="acc-empty">No production pointer exists yet -- nothing to trace lineage from.</p>
      </article>
    );
  }
  type Node = { id: string; label: string; detail: string; tone?: string };
  const productionNode: Node = {
    id: "production",
    label: "Production pointer",
    detail: status.production.candidate_id,
  };
  const trustNodes: Node[] = [];
  if (status.candidate_kind) {
    trustNodes.push({ id: "candidate", label: "Verified base-model candidate", detail: candidate?.upstream_model_id ?? status.production.candidate_id });
    if (verification) trustNodes.push({ id: "verification", label: "Trust verification", detail: verification.verification_state, tone: verification.verification_state === "verified" ? "acc-tone-native" : "acc-tone-bridged" });
  }
  const evidenceNodes: Node[] = [];
  if (status.latest_v1_run_id) {
    const completed = v1Run?.completed_at ? ` · ${new Date(v1Run.completed_at).toLocaleDateString()}` : "";
    evidenceNodes.push({ id: "v1", label: "AtlasBench V1", detail: `${status.latest_v1_total_passed ?? "?"}/${status.latest_v1_total_tasks ?? "?"}${completed}`, tone: "acc-tone-native" });
  }
  if (status.latest_operational_cert_run_id) {
    const critical = status.latest_operational_cert_critical_failures ?? 0;
    const completed = opcertRun?.completed_at ? ` · ${new Date(opcertRun.completed_at).toLocaleDateString()}` : "";
    evidenceNodes.push({
      id: "opcert",
      label: `Operational Certification${completed}`,
      detail: `${status.latest_operational_cert_total_passed ?? "?"}/${status.latest_operational_cert_total_scenarios ?? "?"}${critical > 0 ? ` · ${critical} critical` : ""}`,
      tone: critical > 0 ? "acc-tone-unavailable" : "acc-tone-bridged",
    });
  }
  const corpusNodes: Node[] = [];
  if (corpus.systemSeed) corpusNodes.push({ id: "seed", label: "System seed corpus", detail: `${corpus.systemSeed.example_count} examples · ${corpus.systemSeed.seed_version}` });
  if (corpus.syntheticTeacher) corpusNodes.push({ id: "teacher", label: "Synthetic teacher corpus", detail: `${corpus.syntheticTeacher.example_count} examples · ${corpus.syntheticTeacher.generation_policy_version}` });
  if (corpus.combinedSft) corpusNodes.push({ id: "combined", label: "Combined SFT release", detail: `${corpus.combinedSft.total_sft_count} records · ${corpus.combinedSft.version_id}` });

  return (
    <article className="acc-panel acc-panel-wide">
      <h2>System Cortex</h2>
      <p className="acc-cortex-caption">Real persisted lineage -- production trust, bench and certification evidence, and the training corpus. No hidden reasoning; every node below is a durable record.</p>
      <div className="acc-cortex">
        <ol className="acc-lineage">
          <LineageItem node={productionNode} />
          {trustNodes.map((node) => (
            <LineageItem key={node.id} node={node} indent />
          ))}
        </ol>
        {evidenceNodes.length ? (
          <ol className="acc-lineage acc-lineage-branch">
            {evidenceNodes.map((node) => (
              <LineageItem key={node.id} node={node} />
            ))}
          </ol>
        ) : (
          <p className="acc-empty">No bench or operational-cert evidence recorded for this candidate yet.</p>
        )}
        {corpusNodes.length ? (
          <>
            <p className="acc-cortex-caption acc-cortex-caption-secondary">Training corpus (independent of current production identity)</p>
            <ol className="acc-lineage acc-lineage-branch">
              {corpusNodes.map((node) => (
                <LineageItem key={node.id} node={node} />
              ))}
            </ol>
          </>
        ) : null}
      </div>
    </article>
  );
}

function LineageItem({ node, indent }: { node: { id: string; label: string; detail: string; tone?: string }; indent?: boolean }) {
  return (
    <li className={`acc-lineage-node ${node.tone ?? ""} ${indent ? "acc-lineage-indent" : ""}`}>
      <span className="acc-lineage-dot" aria-hidden="true" />
      <div>
        <strong>{node.label}</strong>
        <p className="acc-mono">{node.detail}</p>
      </div>
    </li>
  );
}

/**
 * Real, recorded Atlas run history -- newest first, from `GET /runs` (a
 * thin id list) resolved into full run detail per id. Nothing here is
 * simulated: an empty list means no run has ever been recorded, not that
 * this panel is hiding activity. Expanding a run reuses the exact same
 * pipeline/specialist/tool/guardrail components the live per-run workspace
 * below uses, over the same durable `plan.steps`/`events` data.
 */
function RunActivityPanel({
  runs,
  failed,
  roster,
  memories,
  feedbackByRun,
}: {
  runs: AtlasRunResponse[];
  failed: boolean;
  roster: AtlasSpecialistIdentity[];
  memories: AtlasMemoryRecord[];
  feedbackByRun: Record<string, AtlasFeedbackEvent[]>;
}) {
  const [openRunId, setOpenRunId] = useState<string | null>(null);
  return (
    <article className="acc-panel acc-panel-wide">
      <h2>Run activity</h2>
      {failed ? (
        <p className="acc-empty">Could not reach the Atlas run history endpoint.</p>
      ) : !runs.length ? (
        <p className="acc-empty">
          No Atlas investigation has been recorded yet. Real specialist, tool, and guardrail activity for any run will appear here as soon
          as one exists -- this panel never simulates activity that isn&apos;t actually happening.
        </p>
      ) : (
        <ul className="acc-run-list">
          {runs.map((run) => {
            const open = openRunId === run.run_id;
            return (
              <li key={run.run_id}>
                <button type="button" className="acc-run-summary" aria-expanded={open} onClick={() => setOpenRunId(open ? null : run.run_id)}>
                  <strong>{run.plan.objective}</strong>
                  <span className={`migration-chip ${run.plan.state === "completed" ? "ready" : run.plan.state === "failed" ? "unavailable" : "bridged"}`}>
                    {(run.plan.state ?? "unknown").replaceAll("_", " ")}
                  </span>
                  <span className="acc-mono">{run.plan.dataset_id}</span>
                  <span className="acc-mono">{run.created_at ? new Date(run.created_at).toLocaleString() : ""}</span>
                </button>
                {open ? (
                  <div className="acc-run-detail">
                    <PipelineStepper run={run} />
                    <SpecialistActivity run={run} roster={roster} />
                    <ToolTimeline run={run} />
                    <RunGuardrailPanel run={run} />
                    <EvidencePanel run={run} />
                    <RunMemoryTrace run={run} memories={memories} feedback={feedbackByRun[run.run_id] ?? []} />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}

const TRUST_STAGE_LABELS: Record<string, string> = { registered: "Registered", verified: "Verified", runtime_bound: "Runtime bound", benchmarked: "Benchmarked", opcert: "Operational Certification", production: "Production", rollback: "Restored via rollback" };

/** A real lifecycle read off already-established facts -- nothing here
 * decides eligibility; it mirrors the same `critical == 0 && pass rate >=
 * 90%` rule the server's own promotion gate enforces, purely for display. */
function TrustPanel({
  status,
  candidate,
  verification,
  history,
  benchRuns,
}: {
  status: AtlasProductionTrustStatus | null;
  candidate: AtlasVerifiedBaseModelCandidate | null;
  verification: AtlasBaseModelVerification | null;
  history: AtlasProductionPointer[];
  benchRuns: AtlasBenchSuiteRun[];
}) {
  const critical = status?.latest_operational_cert_critical_failures ?? 0;
  const passed = status?.latest_operational_cert_total_passed ?? 0;
  const total = status?.latest_operational_cert_total_scenarios ?? 0;
  const opcertRun = Boolean(status?.latest_operational_cert_run_id);
  const eligible = opcertRun && critical === 0 && total > 0 && passed / total >= 0.9;
  const stages = status?.production
    ? [
        { id: "registered", reached: Boolean(status.candidate_kind) },
        { id: "verified", reached: status.trust_verification_state === "verified" },
        { id: "runtime_bound", reached: Boolean(status.runtime_model_digest) },
        { id: "benchmarked", reached: benchRuns.length > 0 || Boolean(status.latest_v1_run_id) },
        { id: "opcert", reached: opcertRun },
        { id: "production", reached: true },
      ]
    : [];
  return (
    <article className="acc-panel">
      <h2>Model trust</h2>
      {!status?.production ? (
        <p className="acc-empty">No production candidate to show trust for yet.</p>
      ) : (
        <>
          <ol className="acc-trust-timeline" aria-label="Model trust lifecycle">
            {stages.map((stage) => (
              <li key={stage.id} className={stage.reached ? "is-reached" : ""}>{TRUST_STAGE_LABELS[stage.id]}</li>
            ))}
            <li className={opcertRun ? (eligible ? "is-reached" : "is-blocked") : ""}>
              {opcertRun ? (eligible ? "Promotion eligible" : "Promotion blocked") : "Promotion pending"}
              {opcertRun && !eligible ? <small>{critical > 0 ? `${critical} critical` : "below 90%"}</small> : null}
            </li>
            {status.production.is_rollback ? <li className="is-current">{TRUST_STAGE_LABELS.rollback}<small>{status.production.reason}</small></li> : null}
          </ol>
          <dl className="acc-facts">
            <div>
              <dt>Runtime model</dt>
              <dd>{status.runtime_model ?? "unknown"}</dd>
            </div>
            <div>
              <dt>Candidate kind</dt>
              <dd>{status.candidate_kind ?? "legacy / bootstrap"}</dd>
            </div>
            <div>
              <dt>Trust state</dt>
              <dd>{status.trust_verification_state ?? "not applicable"}</dd>
            </div>
          </dl>
          {candidate ? (
            <details className="acc-details">
              <summary>Technical identity</summary>
              <dl className="acc-facts">
                <div>
                  <dt>Upstream model</dt>
                  <dd>{candidate.upstream_model_id}</dd>
                </div>
                <div>
                  <dt>Revision</dt>
                  <dd className="acc-mono">{candidate.upstream_revision}</dd>
                </div>
                <div>
                  <dt>License</dt>
                  <dd>{candidate.license}</dd>
                </div>
                <div>
                  <dt>Candidate ID</dt>
                  <dd className="acc-mono">{candidate.candidate_id}</dd>
                </div>
                {verification ? (
                  <>
                    <div>
                      <dt>Verification ID</dt>
                      <dd className="acc-mono">{verification.verification_id}</dd>
                    </div>
                    <div>
                      <dt>Runtime digest</dt>
                      <dd className="acc-mono">{verification.live_runtime_digest ?? "unrecorded"}</dd>
                    </div>
                    <div>
                      <dt>Manifest digest</dt>
                      <dd className="acc-mono">{verification.live_manifest_digest ?? "unrecorded"}</dd>
                    </div>
                    <div>
                      <dt>Candidate fingerprint</dt>
                      <dd className="acc-mono">{verification.aggregate_candidate_fingerprint ?? "unrecorded"}</dd>
                    </div>
                  </>
                ) : null}
              </dl>
            </details>
          ) : null}
          {history.length > 1 ? (
            <details className="acc-details">
              <summary>Promotion history ({history.length})</summary>
              <ul className="acc-scenario-list">
                {history.map((pointer) => (
                  <li key={pointer.event_id}>
                    <strong className="acc-mono">{pointer.candidate_id}</strong>
                    {pointer.is_rollback ? <span> · rollback</span> : null}
                    <p>{pointer.reason}</p>
                    <small>{new Date(pointer.promoted_at).toLocaleString()}</small>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      )}
    </article>
  );
}

function CategoryMatrix({ scores }: { scores: AtlasBenchSuiteRun["category_scores"] }) {
  if (!scores?.length) return null;
  return (
    <table className="acc-matrix">
      <thead>
        <tr>
          <th scope="col">Category</th>
          <th scope="col">Passed</th>
        </tr>
      </thead>
      <tbody>
        {scores.map((score) => (
          <tr key={score.category}>
            <td>{score.category.replaceAll("_", " ")}</td>
            <td>{score.passed}/{score.total}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** One section per real corpus_version recorded for this candidate --
 * V1's own numbers come from the already-trusted current-status fields;
 * any other corpus (V2 holdout, or a future wave) is discovered purely
 * from `GET /bench/runs-by-candidate/{id}`, never a hardcoded run id. */
function BenchPanel({ status, run, candidateRuns }: { status: AtlasProductionTrustStatus | null; run: AtlasBenchSuiteRun | null; candidateRuns: AtlasBenchSuiteRun[] }) {
  const shownVersion = run?.corpus_version ?? null;
  const otherVersions = [...new Map(candidateRuns.filter((item) => item.corpus_version !== shownVersion).map((item) => [item.corpus_version, item])).values()].sort((a, b) =>
    a.corpus_version.localeCompare(b.corpus_version)
  );
  return (
    <article className="acc-panel acc-panel-wide">
      <h2>AtlasBench</h2>
      {!status?.latest_v1_run_id ? (
        <p className="acc-empty">No AtlasBench run recorded for the current production candidate yet.</p>
      ) : (
        <>
          <div className="acc-bench-corpus">
            <h3 className="acc-cortex-caption-secondary">{run?.corpus_version ?? "primary corpus"}</h3>
            <p className="acc-score">
              {status.latest_v1_total_passed ?? "?"} / {status.latest_v1_total_tasks ?? "?"}
            </p>
            <CategoryMatrix scores={run?.category_scores} />
          </div>
          {otherVersions.length ? (
            otherVersions.map((item) => (
              <div className="acc-bench-corpus" key={item.corpus_version}>
                <h3 className="acc-cortex-caption-secondary">{item.corpus_version}</h3>
                <p className="acc-score">
                  {item.total_passed} / {item.total_tasks}
                </p>
                <CategoryMatrix scores={item.category_scores} />
              </div>
            ))
          ) : (
            <p className="acc-cortex-caption">No additional-corpus AtlasBench run (for example, a V2 holdout) is recorded for this candidate yet.</p>
          )}
        </>
      )}
    </article>
  );
}

function OperationalCertPanel({ status, run }: { status: AtlasProductionTrustStatus | null; run: AtlasOperationalSuiteRun | null }) {
  if (!status?.latest_operational_cert_run_id) {
    return (
      <article className="acc-panel">
        <h2>Operational Certification</h2>
        <p className="acc-empty">No live Operational Certification run recorded for the current production candidate yet.</p>
      </article>
    );
  }
  const critical = status.latest_operational_cert_critical_failures ?? 0;
  const passed = status.latest_operational_cert_total_passed ?? 0;
  const total = status.latest_operational_cert_total_scenarios ?? 0;
  const certified = critical === 0 && total > 0 && passed / total >= 0.9;
  const failed: AtlasOperationalScenarioResult[] = (run?.scenario_results ?? []).filter((item) => !item.passed);
  return (
    <article className={`acc-panel ${certified ? "acc-tone-native" : "acc-tone-bridged"}`}>
      <h2>Operational Certification</h2>
      <p className="acc-score">
        {passed} / {total}
      </p>
      <p className="acc-status-line">{certified ? "PASSED" : critical > 0 ? `${critical} critical failure(s)` : "below threshold"}</p>
      {run ? (
        <dl className="acc-facts">
          <div>
            <dt>Suite</dt>
            <dd className="acc-mono">{run.suite_version}</dd>
          </div>
          <div>
            <dt>Run ID</dt>
            <dd className="acc-mono">{run.run_id}</dd>
          </div>
          <div>
            <dt>Completed</dt>
            <dd>{new Date(run.completed_at).toLocaleString()}</dd>
          </div>
        </dl>
      ) : null}
      {failed.length ? (
        <details className="acc-details">
          <summary>
            {failed.length} scenario{failed.length === 1 ? "" : "s"} not passed
          </summary>
          <ul className="acc-scenario-list">
            {failed.map((item) => (
              <li key={item.scenario_id} className={item.critical_failure ? "acc-tone-unavailable" : ""}>
                <strong>{item.scenario_id.replaceAll("_", " ")}</strong>
                {item.critical_failure ? <span className="acc-mono"> · {item.critical_failure.replaceAll("_", " ")}</span> : null}
                {item.detail ? <p>{item.detail}</p> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </article>
  );
}

function CorpusPanel({ corpus }: { corpus: CorpusState }) {
  const summary = corpus.summary;
  return (
    <article className="acc-panel acc-panel-wide">
      <h2>Atlas Intelligence Lab</h2>
      <p className="acc-cortex-caption">Every SFT source class stays auditable on its own -- never blended into one indistinguishable pool.</p>
      <dl className="acc-facts">
        <div>
          <dt>System seed</dt>
          <dd>{corpus.systemSeed ? `${corpus.systemSeed.example_count} reviewed examples (${corpus.systemSeed.seed_version})` : "not released"}</dd>
        </div>
        <div>
          <dt>Synthetic teacher</dt>
          <dd>
            {corpus.syntheticTeacher
              ? `${corpus.syntheticTeacher.example_count} examples (${corpus.syntheticTeacher.generation_policy_version})`
              : "not released"}
          </dd>
        </div>
        <div>
          <dt>History-derived (verified)</dt>
          <dd>{summary ? `${summary.verified_history_examples} eligible examples` : "not computed"}</dd>
        </div>
        <div>
          <dt>User corrections</dt>
          <dd>{summary ? `${summary.user_correction_examples} eligible examples` : "not computed"}</dd>
        </div>
        <div>
          <dt>Combined SFT</dt>
          <dd>
            {corpus.combinedSft
              ? `${corpus.combinedSft.total_sft_count} records · ${corpus.combinedSft.train_count} train / ${corpus.combinedSft.validation_count} val / ${corpus.combinedSft.test_count} test`
              : "not released"}
          </dd>
        </div>
      </dl>
      {corpus.systemSeed?.domain_counts?.length ? (
        <div className="acc-bars" aria-label="System seed distribution by domain">
          {(() => {
            const counts = corpus.systemSeed!.domain_counts!;
            const max = Math.max(...counts.map((entry) => entry.example_count));
            return counts.map((item) => (
              <div key={item.domain} className="acc-bar-row">
                <span>{item.domain.replaceAll("_", " ")}</span>
                <span className="acc-bar-track"><span className="acc-bar-fill" style={{ width: `${max ? (item.example_count / max) * 100 : 0}%` }} /></span>
                <span className="acc-mono">{item.example_count}</span>
              </div>
            ));
          })()}
        </div>
      ) : null}
      {corpus.combinedSft ? (
        <details className="acc-details">
          <summary>Provenance hashes</summary>
          <dl className="acc-facts">
            <div>
              <dt>Version</dt>
              <dd className="acc-mono">{corpus.combinedSft.version_id}</dd>
            </div>
            <div>
              <dt>Aggregate content hash</dt>
              <dd className="acc-mono">{corpus.combinedSft.aggregate_content_hash}</dd>
            </div>
          </dl>
        </details>
      ) : null}
    </article>
  );
}

/**
 * System-wide "what does ATLAS know" view: real Atlas memory (`GET
 * /memories`, grouped by its real knowledge_class, sensitivity-gated),
 * real corrections/feedback (`GET /feedback/recent`), and whether
 * document/RAG retrieval is even configured (`GET /retrieval/capability`
 * -- system-wide, no project needed). Project-scoped RAG chunk browsing
 * (`GET /retrieval/chunks`) is not shown here: it requires a project_id
 * this application has no real "current project" concept to supply, and
 * inventing one would be exactly the fabricated relationship this panel
 * exists to avoid.
 */
function SystemMemoryPanel({
  memories,
  feedback,
  rag,
  failed,
}: {
  memories: AtlasMemoryRecord[];
  feedback: AtlasFeedbackEvent[];
  rag: AtlasEmbeddingCapability | null;
  failed: boolean;
}) {
  const groups = groupMemoriesByClass(memories);
  return (
    <article className="acc-panel acc-panel-wide acc-system-memory" aria-label="Atlas memory and knowledge">
      <h2>Atlas memory &amp; knowledge</h2>
      {failed ? (
        <p className="acc-empty">Could not reach the Atlas memory endpoints.</p>
      ) : (
        <>
          {groups.length ? (
            groups.map((group) => (
              <div key={group.knowledgeClass} className="acc-memory-group">
                <h3>{MEMORY_CLASS_LABELS[group.knowledgeClass] ?? group.knowledgeClass.replaceAll("_", " ")}</h3>
                <ul>
                  {group.records.map((record) => (
                    <MemoryRecordItem key={record.memory_id} record={record} />
                  ))}
                </ul>
              </div>
            ))
          ) : (
            <p className="acc-empty">No persisted ATLAS memory is available for this context.</p>
          )}

          <div className="acc-memory-group">
            <h3>Recent corrections &amp; feedback</h3>
            {feedback.length ? (
              <ul>
                {feedback.map((event) => (
                  <FeedbackItem key={event.feedback_id} event={event} />
                ))}
              </ul>
            ) : (
              <p className="acc-empty">No feedback or corrections have been recorded yet.</p>
            )}
          </div>

          <div className="acc-memory-group">
            <h3>Documents &amp; RAG</h3>
            {rag ? (
              <dl className="acc-facts">
                <div>
                  <dt>Retrieval</dt>
                  <dd>{rag.available ? `${rag.provider} · ${rag.model}` : "not configured"}</dd>
                </div>
                <div>
                  <dt>Detail</dt>
                  <dd>{rag.detail}</dd>
                </div>
              </dl>
            ) : (
              <p className="acc-empty">Could not reach the Atlas retrieval capability endpoint.</p>
            )}
            <p className="acc-cortex-caption">
              Project-scoped document chunks exist in the backend but require a project_id this UI has no real project context to supply --
              shown honestly as unavailable here rather than invented.
            </p>
          </div>
        </>
      )}
    </article>
  );
}
