"use client";

import { useEffect, useState } from "react";
import type {
  AtlasBaseModelVerification,
  AtlasBenchSuiteRun,
  AtlasCombinedSftDatasetVersion,
  AtlasCombinedTrainingSourceSummary,
  AtlasProductionTrustStatus,
  AtlasSyntheticTeacherManifest,
  AtlasSystemSeedManifest,
  AtlasVerifiedBaseModelCandidate,
} from "@prism/api-contracts";
import { apiUrl } from "../config/api";

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
 * trust routes, a bench run detail, and the Foundry corpus list routes.
 * Nothing here decides or verifies anything new, and nothing is hardcoded:
 * if production is still the legacy pointer, this honestly says so instead
 * of claiming Qwen is production.
 */
export function AtlasCommandCenter() {
  const [status, setStatus] = useState<AtlasProductionTrustStatus | null>(null);
  const [statusFailed, setStatusFailed] = useState(false);
  const [candidate, setCandidate] = useState<AtlasVerifiedBaseModelCandidate | null>(null);
  const [verification, setVerification] = useState<AtlasBaseModelVerification | null>(null);
  const [v1Run, setV1Run] = useState<AtlasBenchSuiteRun | null>(null);
  const [corpus, setCorpus] = useState<CorpusState>(emptyCorpus);

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

    void loadStatus();
    void loadCorpus();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className="atlas-command-center" aria-label="Atlas command center">
      <Hero status={status} failed={statusFailed} />
      <div className="acc-grid">
        <TrustPanel status={status} candidate={candidate} verification={verification} />
        <BenchPanel status={status} run={v1Run} />
        <OperationalCertPanel status={status} />
        <CorpusPanel corpus={corpus} />
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
  const roleLabel = verified ? "VERIFIED" : status.candidate_kind ? "UNVERIFIED" : "LEGACY";
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

function TrustPanel({
  status,
  candidate,
  verification,
}: {
  status: AtlasProductionTrustStatus | null;
  candidate: AtlasVerifiedBaseModelCandidate | null;
  verification: AtlasBaseModelVerification | null;
}) {
  return (
    <article className="acc-panel">
      <h2>Model trust</h2>
      {!status?.production ? (
        <p className="acc-empty">No production candidate to show trust for yet.</p>
      ) : (
        <>
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
        </>
      )}
    </article>
  );
}

function BenchPanel({ status, run }: { status: AtlasProductionTrustStatus | null; run: AtlasBenchSuiteRun | null }) {
  return (
    <article className="acc-panel">
      <h2>AtlasBench V1</h2>
      {!status?.latest_v1_run_id ? (
        <p className="acc-empty">No AtlasBench V1 run recorded for the current production candidate yet.</p>
      ) : (
        <>
          <p className="acc-score">
            {status.latest_v1_total_passed ?? "?"} / {status.latest_v1_total_tasks ?? "?"}
          </p>
          {run?.category_scores?.length ? (
            <table className="acc-matrix">
              <thead>
                <tr>
                  <th scope="col">Category</th>
                  <th scope="col">Passed</th>
                </tr>
              </thead>
              <tbody>
                {run.category_scores.map((score) => (
                  <tr key={score.category}>
                    <td>{score.category.replaceAll("_", " ")}</td>
                    <td>
                      {score.passed}/{score.total}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </>
      )}
    </article>
  );
}

function OperationalCertPanel({ status }: { status: AtlasProductionTrustStatus | null }) {
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
  return (
    <article className={`acc-panel ${certified ? "acc-tone-native" : "acc-tone-bridged"}`}>
      <h2>Operational Certification</h2>
      <p className="acc-score">
        {passed} / {total}
      </p>
      <p className="acc-status-line">{certified ? "PASSED" : critical > 0 ? `${critical} critical failure(s)` : "below threshold"}</p>
    </article>
  );
}

function CorpusPanel({ corpus }: { corpus: CorpusState }) {
  return (
    <article className="acc-panel">
      <h2>Atlas Intelligence corpus</h2>
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
          <dt>Combined SFT</dt>
          <dd>
            {corpus.combinedSft
              ? `${corpus.combinedSft.total_sft_count} records · ${corpus.combinedSft.train_count} train / ${corpus.combinedSft.validation_count} val / ${corpus.combinedSft.test_count} test`
              : "not released"}
          </dd>
        </div>
      </dl>
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
      {corpus.systemSeed?.domain_counts?.length ? (
        <details className="acc-details">
          <summary>System seed by domain</summary>
          <dl className="acc-facts">
            {corpus.systemSeed.domain_counts.map((item) => (
              <div key={item.domain}>
                <dt>{item.domain.replaceAll("_", " ")}</dt>
                <dd>{item.example_count}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </article>
  );
}
