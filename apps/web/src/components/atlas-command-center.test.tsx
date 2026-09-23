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

// Preserve the established panel evidence fixtures while migrating their transport
// to the aggregate contract. This helper runs only in unit tests.
function stubDashboardFetch(_name: string, source: (input: string | URL) => Promise<Response>) {
  async function read<T>(path: string, fallback: T): Promise<T> {
    const response = await source(`/api/v1/atlas/${path}`);
    return response.ok ? await response.json() as T : fallback;
  }
  vi.stubGlobal("fetch", async (input: string | URL) => {
    if (!String(input).includes("/command-center")) return source(input);
    const status = await read<import("@prism/api-contracts").AtlasProductionTrustStatus | null>("promotion/current-status", null);
    const id = status?.production?.candidate_id;
    const runs = await read<string[]>("runs?limit=8", []);
    const details = await Promise.all(runs.map((runId) => read<import("@prism/api-contracts").AtlasRunResponse | null>(`runs/${runId}`, null)));
    const bench = id ? await read<import("@prism/api-contracts").AtlasBenchSuiteRun[]>(`bench/runs-by-candidate/${id}`, []) : [];
    if (status?.latest_v1_run_id && !bench.length) {
      const primary = await read<import("@prism/api-contracts").AtlasBenchSuiteRun | null>(`bench/runs/detail/${status.latest_v1_run_id}`, null);
      if (primary) bench.push(primary);
    }
    return json({
      generated_at: "2026-09-15T00:00:00Z", sections: {}, status,
      candidate: id ? await read(`base-model-candidates/${id}`, null) : null,
      verification: id ? (await read<unknown[]>(`base-model-candidates/${id}/verification`, []))[0] ?? null : null,
      operational_run: status?.latest_operational_cert_run_id ? await read(`operational-cert/runs/${status.latest_operational_cert_run_id}`, null) : null,
      bench_runs: bench, promotion_history: await read("promotion/history", []),
      system_seed: (await read<unknown[]>("foundry/system-seed", []))[0],
      synthetic_teacher: (await read<unknown[]>("foundry/synthetic-teacher", []))[0],
      combined_sft: (await read<unknown[]>("foundry/combined-sft-datasets", []))[0],
      recent_runs: details.filter((run) => run !== null).map((run) => ({ run_id: run.run_id, dataset_id: run.plan.dataset_id, objective: run.plan.objective, state: run.plan.state, created_at: run.created_at, updated_at: run.updated_at })),
      specialists: await read("specialists", []), memories: await read("memories?limit=50", []),
      feedback: await read("feedback/recent?limit=20", []), retrieval: await read("retrieval/capability", null),
    });
  });
}

describe("Atlas command center", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reports status unknown honestly when the endpoint cannot be reached", async () => {
    stubDashboardFetch("fetch", vi.fn(async () => { throw new Error("offline"); }));
    render(<AtlasCommandCenter />);
    await waitFor(() => expect(screen.getByText("STATUS UNKNOWN")).toBeInTheDocument());
    // A total network failure must read as "failed" everywhere it affects --
    // never silently degrade into the same "nothing here yet" text a truly
    // empty system would show. Every panel driven by the promotion-status
    // fetch (Hero, System Cortex, Model Trust, AtlasBench, Operational
    // Certification) gets its own honest "could not reach" message, as do
    // the run-history, memory, and corpus panels whose own fetches also
    // failed in this scenario.
    const statusEndpointMessages = screen.getAllByText("Could not reach the Atlas promotion status endpoint.");
    expect(statusEndpointMessages.length).toBe(5); // Hero, System Cortex, Model Trust, AtlasBench, Operational Certification
    expect(screen.getByText("Could not reach the Atlas run history endpoint.")).toBeInTheDocument();
    expect(screen.getByText("Could not reach the Atlas memory endpoints.")).toBeInTheDocument();
    expect(screen.getByText("Could not reach the Atlas Foundry corpus endpoints.")).toBeInTheDocument();
  });

  it("shows no production model rather than fabricating one when none has ever been promoted", async () => {
    stubDashboardFetch("fetch", vi.fn(async (input: string | URL) => {
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
    stubDashboardFetch("fetch", vi.fn(async (input: string | URL) => {
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
    stubDashboardFetch(
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
            operational_cert_min_pass_rate: 0.9,
            latest_operational_cert_passed: false,
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
        if (path.includes("/memories")) {
          return json([
            { memory_id: "memory_1", scope: "session", knowledge_class: "project_knowledge", content: "Full private planning content.", source: "planning doc", source_ref: "atlas_recent_1", confidence: "high", timestamp: "2026-01-01T00:00:00Z", sensitivity: "internal", created_at: "2026-01-01T00:00:00Z" },
          ]);
        }
        if (path.includes("/feedback/recent")) {
          return json([{ feedback_id: "atlasfeedback_recent_1", run_id: "atlas_recent_1", kind: "helpful", answer: "Good profile.", created_at: "2026-01-02T00:02:00Z" }]);
        }
        if (path.endsWith("/feedback/runs/atlas_recent_1")) {
          return json([{ feedback_id: "atlasfeedback_recent_1", run_id: "atlas_recent_1", kind: "helpful", answer: "Good profile.", created_at: "2026-01-02T00:02:00Z" }]);
        }
        if (path.includes("/retrieval/capability")) {
          return json({ provider: "lexical", model: "none", revision: "v1", available: false, detail: "Vector embeddings are not configured; deterministic lexical retrieval remains available." });
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
    expect(await within(activityPanel).findByLabelText("Atlas request pipeline")).toBeInTheDocument();
    expect(within(activityPanel).getByLabelText("Atlas specialist activity")).toBeInTheDocument();

    // Per-run memory trace inside the expanded run: the real memory linked
    // via source_ref, and the real feedback from GET /feedback/runs/{id}.
    const runMemoryTrace = within(activityPanel).getByLabelText("Atlas memory used by this run");
    expect(within(runMemoryTrace).getByText("planning doc")).toBeInTheDocument();
    expect(within(runMemoryTrace).getByText("Helpful")).toBeInTheDocument();

    // System-wide memory panel: real grouped memory, real recent feedback,
    // and honest RAG-not-configured/no-project-context disclosure.
    const memoryPanel = screen.getByLabelText("Atlas memory and knowledge");
    expect(within(memoryPanel).getByText("Project Knowledge", { selector: "h3" })).toBeInTheDocument();
    expect(within(memoryPanel).getByText("planning doc")).toBeInTheDocument();
    expect(within(memoryPanel).getByText("Recent corrections & feedback")).toBeInTheDocument();
    expect(within(memoryPanel).getByText("not configured")).toBeInTheDocument();
    expect(within(memoryPanel).getByText(/no real project context to supply/)).toBeInTheDocument();
  });

  describe("Historical run Cortex", () => {
    const historicalRun = {
      run_id: "atlas_hist_1",
      plan: { plan_id: "plan_hist_1", objective: "Investigate churn drivers", dataset_id: "ds_hist", provider: "deterministic", state: "completed", created_at: "2026-01-03T00:00:00Z", steps: [] },
      answer: "Churn correlates with support-ticket volume.",
      council: [],
      evidence: [],
      events: [],
      created_at: "2026-01-03T00:00:00Z",
    };
    const historicalCortex = {
      run_id: "atlas_hist_1",
      generated_at: "2026-01-03T00:00:00Z",
      nodes: [
        { node_id: "run:atlas_hist_1", kind: "run", label: "Atlas run", state: "completed", source_id: "atlas_hist_1" },
        { node_id: "dataset:ds_hist", kind: "dataset", label: "Dataset", state: "recorded", source_id: "ds_hist" },
        { node_id: "specialist:scout", kind: "specialist", label: "Scout", state: "visible", source_id: "scout" },
      ],
      edges: [{ edge_id: "uses", source_node_id: "run:atlas_hist_1", target_node_id: "dataset:ds_hist", relation: "uses" }],
    };

    function mockRunListing(cortexResponse: () => Response | Promise<Response>) {
      return vi.fn(async (input: string | URL) => {
        const path = String(input);
        if (path.includes("/promotion/current-status")) return json({ production: null, candidate_kind: null, runtime_model: null });
        if (path.includes("/specialists")) return json([]);
        if (path.includes("/atlas/runs?limit=8")) return json(["atlas_hist_1"]);
        if (path.endsWith("/atlas/runs/atlas_hist_1/cortex")) return cortexResponse();
        if (path.endsWith("/atlas/runs/atlas_hist_1")) return json(historicalRun);
        if (path.includes("/feedback/runs/atlas_hist_1") || path.includes("/promotion/history")) return json([]);
        return notFound();
      });
    }

    async function expandHistoricalRun(): Promise<HTMLElement> {
      render(<AtlasCommandCenter />);
      const activityPanel = screen.getByText("Run activity").closest("article") as HTMLElement;
      await waitFor(() => expect(within(activityPanel).getByText("Investigate churn drivers")).toBeInTheDocument());
      fireEvent.click(within(activityPanel).getByText("Investigate churn drivers"));
      return activityPanel;
    }

    it("fetches and renders the real persisted Cortex graph on expand, with truthful counts and keyboard-reachable node selection", async () => {
      stubDashboardFetch("fetch", mockRunListing(() => json(historicalCortex)));
      const activityPanel = await expandHistoricalRun();

      const cortex = await within(activityPanel).findByLabelText("Cortex real-state graph");
      // Counts read straight off the fetched graph -- 3 real nodes, 1 real
      // relation -- never a fabricated topology or a hardcoded number.
      expect(within(cortex).getByText(/3 real nodes/)).toBeInTheDocument();
      expect(within(cortex).getByText(/1 real relation/)).toBeInTheDocument();

      // Every satellite is a real, focusable <button> in the accessible
      // mirror list -- keyboard-reachable by construction, never dependent
      // on canvas hit-testing.
      const datasetButton = within(cortex).getByRole("button", { name: "Focus Dataset" });
      datasetButton.focus();
      expect(datasetButton).toHaveFocus();
      fireEvent.click(datasetButton);

      // Selecting it surfaces real selected-node detail, not placeholder text.
      const detail = await within(cortex).findByLabelText("Selected Cortex node");
      expect(within(detail).getByText("dataset")).toBeInTheDocument();
      expect(within(detail).getByText("Dataset")).toBeInTheDocument();
    });

    it("shows a loading state before the historical run's Cortex graph arrives", async () => {
      let resolveCortex!: (response: Response) => void;
      const pending = new Promise<Response>((resolve) => { resolveCortex = resolve; });
      stubDashboardFetch("fetch", mockRunListing(() => pending));
      const activityPanel = await expandHistoricalRun();

      expect(await within(activityPanel).findByText(/Loading this run.s persisted Cortex graph/)).toBeInTheDocument();
      resolveCortex(json(historicalCortex));
      await waitFor(() => expect(within(activityPanel).getByLabelText("Cortex real-state graph")).toBeInTheDocument());
    });

    it("shows an honest unavailable message, without breaking the rest of the run's detail, when the Cortex fetch fails", async () => {
      stubDashboardFetch("fetch", mockRunListing(() => notFound()));
      const activityPanel = await expandHistoricalRun();

      await waitFor(() => expect(within(activityPanel).getByRole("alert")).toHaveTextContent("Could not reach this run's persisted Cortex graph."));
      // The rest of the expanded run's detail still renders -- one failed
      // fetch never takes down the panels that don't depend on it.
      expect(await within(activityPanel).findByLabelText("Atlas request pipeline")).toBeInTheDocument();
    });

    describe("history deep link (Phase 11C)", () => {
      it("auto-expands the linked run already present in the recent list, fetches its real Cortex graph, and focuses a real requested node", async () => {
        stubDashboardFetch("fetch", mockRunListing(() => json(historicalCortex)));
        render(<AtlasCommandCenter deepLinkRunId="atlas_hist_1" deepLinkFocusId="specialist:scout" />);

        // No manual click on the run row: the deep link alone expands it.
        const cortex = await screen.findByLabelText("Cortex real-state graph");
        // The requested id is a real node in this run's fetched graph, so it
        // is selected exactly as a real click on it would select it --
        // never a fabricated/invented selection.
        const detail = await within(cortex).findByLabelText("Selected Cortex node");
        expect(within(detail).getByText("specialist")).toBeInTheDocument();
        expect(within(detail).getByText("Scout")).toBeInTheDocument();
      });

      it("never fabricates a selection when the requested focus id does not exist in the real fetched graph", async () => {
        stubDashboardFetch("fetch", mockRunListing(() => json(historicalCortex)));
        render(<AtlasCommandCenter deepLinkRunId="atlas_hist_1" deepLinkFocusId="specialist:does_not_exist" />);

        const cortex = await screen.findByLabelText("Cortex real-state graph");
        // Give the (absent) focus effect a tick to have run, then assert
        // honestly that nothing got selected -- not even a fallback guess.
        await waitFor(() => expect(within(cortex).getByText(/3 real nodes/)).toBeInTheDocument());
        expect(within(cortex).queryByLabelText("Selected Cortex node")).not.toBeInTheDocument();
      });

      it("resolves a linked run that falls outside the recent-8 list by fetching it directly and merging it into the real list", async () => {
        const olderRun = { ...historicalRun, run_id: "atlas_hist_older", plan: { ...historicalRun.plan, objective: "Investigate an older churn spike" } };
        stubDashboardFetch("fetch", vi.fn(async (input: string | URL) => {
          const path = String(input);
          if (path.includes("/promotion/current-status")) return json({ production: null, candidate_kind: null, runtime_model: null });
          if (path.includes("/specialists")) return json([]);
          if (path.includes("/atlas/runs?limit=8")) return json(["atlas_hist_1"]);
          if (path.endsWith("/atlas/runs/atlas_hist_1/cortex")) return json(historicalCortex);
          if (path.endsWith("/atlas/runs/atlas_hist_1")) return json(historicalRun);
          if (path.endsWith("/atlas/runs/atlas_hist_older/cortex")) return json({ ...historicalCortex, run_id: "atlas_hist_older" });
          if (path.endsWith("/atlas/runs/atlas_hist_older")) return json(olderRun);
          if (path.includes("/feedback/runs/") || path.includes("/promotion/history")) return json([]);
          return notFound();
        }));

        render(<AtlasCommandCenter deepLinkRunId="atlas_hist_older" />);
        const activityPanel = screen.getByText("Run activity").closest("article") as HTMLElement;
        // Resolved by its own real GET /runs/{id} fetch, then merged into
        // the same real list -- and auto-expanded, exactly like a run
        // already in the recent-8 window would be.
        await within(activityPanel).findByText("Investigate an older churn spike");
        await within(activityPanel).findByLabelText("Cortex real-state graph");
        // The recent-8 run is still shown too -- merging never replaces it.
        expect(within(activityPanel).getByText("Investigate churn drivers")).toBeInTheDocument();
      });

      it("shows an honest failure, not a fabricated run, when the linked run truly does not exist", async () => {
        stubDashboardFetch("fetch", vi.fn(async (input: string | URL) => {
          const path = String(input);
          if (path.includes("/promotion/current-status")) return json({ production: null, candidate_kind: null, runtime_model: null });
          if (path.includes("/specialists") || path.includes("/atlas/runs?limit=8")) return json([]);
          return notFound();
        }));
        render(<AtlasCommandCenter deepLinkRunId="atlas_hist_missing" />);
        const activityPanel = screen.getByText("Run activity").closest("article") as HTMLElement;
        await waitFor(() => expect(within(activityPanel).getByRole("alert")).toHaveTextContent("atlas_hist_missing"));
        expect(within(activityPanel).getByRole("alert")).toHaveTextContent("could not be found");
      });
    });

    describe("copy investigation link (Phase 11C)", () => {
      async function expandAndFindCopyButton() {
        stubDashboardFetch("fetch", mockRunListing(() => json(historicalCortex)));
        const activityPanel = await expandHistoricalRun();
        await within(activityPanel).findByLabelText("Cortex real-state graph");
        return within(activityPanel).getByRole("button", { name: "Copy investigation link" });
      }

      it("copies a real shareable link via the browser clipboard when it is available, and truthfully reports success", async () => {
        const writeText = vi.fn(async (_text: string) => undefined);
        Object.defineProperty(window.navigator, "clipboard", { value: { writeText }, configurable: true });
        try {
          const copyButton = await expandAndFindCopyButton();
          fireEvent.click(copyButton);
          await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
          const [copiedLink] = writeText.mock.calls[0]!;
          const url = new URL(copiedLink);
          expect(url.searchParams.get("run_id")).toBe("atlas_hist_1");
          expect(url.searchParams.get("atlas_panel")).toBe("history");
          await waitFor(() => expect(screen.getByText("Link copied to your clipboard.")).toBeInTheDocument());
        } finally {
          Reflect.deleteProperty(window.navigator, "clipboard");
        }
      });

      it("never claims success when the clipboard write actually fails, and offers a real manual-copy fallback instead", async () => {
        const writeText = vi.fn(async () => { throw new Error("denied"); });
        Object.defineProperty(window.navigator, "clipboard", { value: { writeText }, configurable: true });
        try {
          const copyButton = await expandAndFindCopyButton();
          fireEvent.click(copyButton);
          await waitFor(() => expect(screen.getByText(/Couldn.t copy automatically/)).toBeInTheDocument());
          const fallback = screen.getByLabelText("Investigation link") as HTMLInputElement;
          expect(fallback.value).toContain("run_id=atlas_hist_1");
          expect(fallback.value).toContain("atlas_panel=history");
        } finally {
          Reflect.deleteProperty(window.navigator, "clipboard");
        }
      });

      it("never claims a clipboard attempt was made when no clipboard API exists, and still offers the real link to copy manually", async () => {
        // jsdom provides no navigator.clipboard by default -- an honest
        // stand-in for a non-secure-context or unsupported browser.
        expect((window.navigator as { clipboard?: unknown }).clipboard).toBeUndefined();
        const copyButton = await expandAndFindCopyButton();
        fireEvent.click(copyButton);
        await waitFor(() => expect(screen.getByText(/Clipboard access isn.t available here/)).toBeInTheDocument());
        const fallback = screen.getByLabelText("Investigation link") as HTMLInputElement;
        expect(fallback.value).toContain("run_id=atlas_hist_1");
      });
    });
  });
});


it("renders partial summary availability with one initial request and recovers", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(json({ generated_at: "2026-09-15T00:00:00Z", sections: { trust: { state: "error", detail: "Trust unavailable", observed_at: "2026-09-15T00:00:00Z" }, runs: { state: "available", detail: "Read from records", observed_at: "2026-09-15T00:00:00Z" } }, recent_runs: [] }))
    .mockResolvedValueOnce(json({ generated_at: "2026-09-15T00:00:00Z", sections: {}, status: { production: null }, recent_runs: [] }));
  vi.stubGlobal("fetch", fetcher);
  render(<AtlasCommandCenter />);
  await screen.findByText("STATUS UNKNOWN");
  expect(fetcher).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByText("Section availability and freshness"));
  expect(screen.getByText(/Trust unavailable/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Refresh Command Center" }));
  await screen.findByText("NO PRODUCTION MODEL");
  expect(fetcher).toHaveBeenCalledTimes(2);
});
