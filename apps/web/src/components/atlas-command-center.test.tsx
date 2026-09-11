import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AtlasCommandCenter } from "./atlas-command-center";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function notFound(): Response {
  return new Response(JSON.stringify({ detail: "not found" }), { status: 404, headers: { "content-type": "application/json" } });
}

describe("Atlas command center", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reports status unknown honestly when the endpoint cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    render(<AtlasCommandCenter />);
    await waitFor(() => expect(screen.getByText("STATUS UNKNOWN")).toBeInTheDocument());
  });

  it("shows no production model rather than fabricating one when none has ever been promoted", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/promotion/current-status")) return json({ production: null, candidate_kind: null, runtime_model: null });
      if (path.includes("/specialists") || path.includes("/atlas/runs?limit=8") || path.includes("/promotion/history")) return json([]);
      return notFound();
    }));
    render(<AtlasCommandCenter />);
    await waitFor(() => expect(screen.getByText("NO PRODUCTION MODEL")).toBeInTheDocument());
    expect(screen.getByText(/No production pointer exists yet/)).toBeInTheDocument();
    expect(screen.getByText(/No Atlas investigation has been recorded yet/)).toBeInTheDocument();
  });

  it("never labels a legacy production pointer as verified, and offers no fake live activity", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/promotion/current-status")) {
        return json({
          production: { event_id: "evt_1", candidate_id: "legacy", reason: "bootstrap", promoted_at: "2026-01-01T00:00:00Z" },
          candidate_kind: null,
          runtime_model: "legacy-model:latest",
        });
      }
      if (path.includes("/specialists") || path.includes("/atlas/runs?limit=8") || path.includes("/promotion/history")) return json([]);
      return notFound();
    }));
    render(<AtlasCommandCenter />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "legacy-model:latest" })).toBeInTheDocument());
    expect(screen.getByText("LEGACY")).toBeInTheDocument();
    expect(screen.getByText(/No Atlas investigation has been recorded yet/)).toBeInTheDocument();
    // The legacy pointer has a candidate_id but no trust registry entry --
    // the System Cortex must show the production node without inventing a
    // candidate/verification lineage that was never established.
    expect(screen.getByText("legacy")).toBeInTheDocument();
    expect(screen.queryByText("Verified base-model candidate")).not.toBeInTheDocument();
  });

  it("renders real verified-production evidence pulled from the existing backend routes, never fabricated", async () => {
    const candidateId = "basemodel_test";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL) => {
        const path = String(input);
        if (path.includes("/promotion/current-status")) {
          return json({
            production: { event_id: "evt_2", candidate_id: candidateId, reason: "final promotion", promoted_at: "2026-01-01T00:00:00Z" },
            candidate_kind: "verified_base_model",
            runtime_model: "qwen3-test:latest",
            trust_verification_state: "verified",
            latest_v1_run_id: "benchrun_1",
            latest_v1_total_passed: 90,
            latest_v1_total_tasks: 90,
            latest_operational_cert_run_id: "opcert_1",
            latest_operational_cert_total_passed: 19,
            latest_operational_cert_total_scenarios: 23,
            latest_operational_cert_critical_failures: 0,
          });
        }
        if (path.endsWith(`/base-model-candidates/${candidateId}`)) {
          return json({
            candidate_id: candidateId,
            upstream_model_id: "Qwen/Qwen3-4B-Instruct-2507",
            upstream_revision: "rev-1",
            license: "Apache-2.0",
            official_source: "https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507",
            runtime_model: "qwen3-test:latest",
            declared_runtime_digest: "sha256:abc",
            created_at: "2026-01-01T00:00:00Z",
          });
        }
        if (path.endsWith(`/base-model-candidates/${candidateId}/verification`)) {
          return json([
            {
              verification_id: "basemodelverify_1",
              candidate_id: candidateId,
              upstream_model_id: "Qwen/Qwen3-4B-Instruct-2507",
              upstream_revision: "rev-1",
              license: "Apache-2.0",
              runtime_model: "qwen3-test:latest",
              live_runtime_digest: "sha256:abc",
              live_manifest_digest: "sha256:manifest",
              aggregate_candidate_fingerprint: "fp-123",
              verification_state: "verified",
              created_at: "2026-01-01T00:00:00Z",
            },
          ]);
        }
        if (path.endsWith("/bench/runs/detail/benchrun_1")) {
          return json({
            run_id: "benchrun_1",
            subject_id: "subject_1",
            corpus_version: "atlasbench-v1",
            corpus_hash: "a".repeat(64),
            total_tasks: 90,
            total_passed: 90,
            category_scores: [{ category: "sql", total: 10, passed: 10 }],
            started_at: "2026-01-01T00:00:00Z",
            completed_at: "2026-01-01T00:00:00Z",
          });
        }
        if (path.endsWith("/operational-cert/runs/opcert_1")) {
          return json({
            run_id: "opcert_1",
            suite_version: "atlas-operational-cert-wave2",
            suite_hash: "e".repeat(64),
            subject_id: "operational_candidate_basemodel_test",
            subject_kind: "candidate",
            candidate_id: candidateId,
            total_scenarios: 23,
            total_passed: 19,
            critical_failure_count: 0,
            started_at: "2026-01-01T00:00:00Z",
            completed_at: "2026-01-01T00:05:00Z",
            scenario_results: [
              { scenario_id: "evidence_freshness_conflict", passed: false, tool_call_count: 0, elapsed_ms: 10, detail: "chose cached over fresh" },
              { scenario_id: "dataset_profiling", passed: true, tool_call_count: 1, elapsed_ms: 10 },
            ],
          });
        }
        if (path.includes("/foundry/system-seed") && !path.includes("release")) {
          return json([{ seed_version: "seed-v1", created_at: "2026-01-01T00:00:00Z", example_count: 125, domain_counts: [{ domain: "sql", example_count: 20 }], aggregate_content_hash: "b".repeat(64), leakage_guard_passed: true }]);
        }
        if (path.includes("/foundry/synthetic-teacher") && !path.includes("release")) {
          return json([{ generation_policy_version: "teacher-v1", created_at: "2026-01-01T00:00:00Z", example_count: 80, aggregate_content_hash: "c".repeat(64), atlasbench_v1_leakage_guard_passed: true, atlasbench_v2_leakage_guard_passed: true, intra_corpus_duplicate_guard_passed: true, license_validation_passed: true, secret_scan_passed: true }]);
        }
        if (path.includes("/foundry/combined-sft-datasets")) {
          return json([{ version_id: "combined-v1", seed_version: "seed-v1", system_seed_count: 125, atlas_history_count: 40, synthetic_teacher_count: 80, total_sft_count: 245, train_count: 200, validation_count: 25, test_count: 20, aggregate_content_hash: "d".repeat(64), created_at: "2026-01-01T00:00:00Z" }]);
        }
        if (path.includes("training-datasets:combined-summary")) {
          return json({ seed_version: "seed-v1", system_seed_examples: 125, verified_history_examples: 40, user_correction_examples: 5, synthetic_teacher_examples: 80, total_eligible: 250, computed_at: "2026-01-01T00:00:00Z" });
        }
        if (path.includes("/specialists")) {
          return json([
            { specialist: "scout", display_name: "Scout", role: "Dataset reconnaissance and profiling", visible: true },
            { specialist: "curator", display_name: "Curator", role: "Data quality and cleaning readiness", visible: true },
          ]);
        }
        if (path.includes("/atlas/runs?limit=8")) return json(["atlas_recent_1"]);
        if (path.endsWith("/atlas/runs/atlas_recent_1")) {
          return json({
            run_id: "atlas_recent_1",
            plan: { plan_id: "plan_recent_1", objective: "Profile the quarterly dataset", dataset_id: "ds_recent", provider: "deterministic", state: "completed", created_at: "2026-01-02T00:00:00Z", steps: [] },
            answer: "Atlas completed a deterministic first-pass assessment.",
            council: [],
            evidence: [],
            events: [],
            created_at: "2026-01-02T00:00:00Z",
          });
        }
        if (path.includes("/promotion/history")) {
          return json([
            { event_id: "evt_2", candidate_id: candidateId, reason: "final promotion", promoted_at: "2026-01-01T00:00:00Z" },
            { event_id: "evt_0", candidate_id: "legacy", reason: "bootstrap", promoted_at: "2025-06-01T00:00:00Z" },
          ]);
        }
        if (path.includes(`/bench/runs-by-candidate/${candidateId}`)) {
          return json([
            { run_id: "benchrun_1", subject_id: "subject_1", corpus_version: "atlasbench-v1", corpus_hash: "a".repeat(64), total_tasks: 90, total_passed: 90, category_scores: [{ category: "sql", total: 10, passed: 10 }], started_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:00Z", candidate_id: candidateId },
            { run_id: "benchrun_v2", subject_id: "subject_1", corpus_version: "atlasbench-v2-holdout-wave3", corpus_hash: "f".repeat(64), total_tasks: 80, total_passed: 78, category_scores: [{ category: "sql", total: 8, passed: 8 }], started_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:00Z", candidate_id: candidateId },
          ]);
        }
        return notFound();
      })
    );

    render(<AtlasCommandCenter />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "qwen3-test:latest" })).toBeInTheDocument());
    expect(screen.getByText("VERIFIED")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("90 / 90")).toBeInTheDocument());
    expect(screen.getByText("19 / 23")).toBeInTheDocument();
    expect(screen.queryByText("PASSED")).not.toBeInTheDocument();
    expect(screen.getByText("below threshold")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/125 reviewed examples/)).toBeInTheDocument());

    // System Cortex: real lineage, built only from fetched data.
    const cortex = screen.getByText("System Cortex").closest("article") as HTMLElement;
    expect(within(cortex).getByText(candidateId)).toBeInTheDocument();
    expect(within(cortex).getByText("Verified base-model candidate")).toBeInTheDocument();
    expect(within(cortex).getByText(/combined-v1/)).toBeInTheDocument();

    // Operational Certification panel surfaces the real failed scenario, not a hardcoded pass.
    const opcertPanel = screen.getByText("Operational Certification", { selector: "h2" }).closest("article") as HTMLElement;
    const failedSummary = within(opcertPanel).getByText(/1 scenario not passed/);
    expect(failedSummary).toBeInTheDocument();
    failedSummary.click();
    expect(within(opcertPanel).getByText(/evidence freshness conflict/)).toBeInTheDocument();
    expect(within(opcertPanel).getByText("chose cached over fresh")).toBeInTheDocument();

    // AtlasBench: V1's number still comes from the trusted current-status
    // fields, and V2 is discovered purely via runs-by-candidate -- never a
    // hardcoded run id or corpus label.
    const benchPanel = screen.getByText("AtlasBench", { selector: "h2" }).closest("article") as HTMLElement;
    expect(within(benchPanel).getByText("atlasbench-v1")).toBeInTheDocument();
    expect(within(benchPanel).getByText("atlasbench-v2-holdout-wave3")).toBeInTheDocument();
    expect(within(benchPanel).getByText("78 / 80")).toBeInTheDocument();

    // Model trust lifecycle: real stages reached from already-established facts.
    const trustPanel = screen.getByText("Model trust").closest("article") as HTMLElement;
    const timeline = within(trustPanel).getByLabelText("Model trust lifecycle");
    expect(within(timeline).getByText("Registered").closest("li")).toHaveClass("is-reached");
    expect(within(timeline).getByText("Verified").closest("li")).toHaveClass("is-reached");
    expect(within(timeline).getByText("Promotion blocked").closest("li")).toHaveClass("is-blocked");
    expect(within(trustPanel).getByText(/Promotion history/)).toBeInTheDocument();

    // Run activity: a real recorded run, expandable into the same real
    // pipeline/specialist/tool/guardrail views the per-run workspace uses.
    const activityPanel = screen.getByText("Run activity").closest("article") as HTMLElement;
    const runRow = within(activityPanel).getByText("Profile the quarterly dataset");
    fireEvent.click(runRow);
    expect(within(activityPanel).getByLabelText("Atlas request pipeline")).toBeInTheDocument();
    expect(within(activityPanel).getByLabelText("Atlas specialist activity")).toBeInTheDocument();
  });
});
