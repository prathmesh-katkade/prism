import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvolutionWorkspace } from "./evolution-workspace";

const emptyResponses: Record<string, unknown> = {
  "/api/v1/atlas/foundry/capability": { backend: "soup", soup_available: false, can_train: false, can_cancel: false, can_pause: false, detail: "Soup is not installed in this environment." },
  "/api/v1/atlas/bench/corpus/summary": { corpus_version: "atlasbench-v1", corpus_hash: "a".repeat(64), total_tasks: 90, category_counts: [{ category: "factual_recall", task_count: 9 }] },
  "/api/v1/atlas/promotion/current": null,
  "/api/v1/atlas/promotion/history": [],
  "/api/v1/atlas/foundry/candidates": [],
  "/api/v1/atlas/foundry/training-datasets": [],
  "/api/v1/atlas/foundry/preference-datasets": [],
  "/api/v1/atlas/foundry/jobs": [],
  "/api/v1/atlas/adapters/capabilities": [],
};

const populatedResponses: Record<string, unknown> = {
  "/api/v1/atlas/foundry/capability": { backend: "soup", soup_available: true, soup_version: "0.73.3", can_train: true, can_cancel: true, can_pause: false, detail: "Soup is installed and ready." },
  "/api/v1/atlas/bench/corpus/summary": { corpus_version: "atlasbench-v1", corpus_hash: "a".repeat(64), total_tasks: 90, category_counts: [{ category: "factual_recall", task_count: 9 }] },
  "/api/v1/atlas/promotion/current": { event_id: "evt_1", candidate_id: "cand_1", previous_candidate_id: null, decision_id: "dec_1", is_rollback: false, reason: "Improved factual recall with no critical regression.", promoted_at: "2026-09-01T00:00:00Z" },
  "/api/v1/atlas/promotion/history": [
    { event_id: "evt_1", candidate_id: "cand_1", previous_candidate_id: null, decision_id: "dec_1", is_rollback: false, reason: "Improved factual recall with no critical regression.", promoted_at: "2026-09-01T00:00:00Z" },
  ],
  "/api/v1/atlas/foundry/candidates": [
    { candidate_id: "cand_1", job_id: "job_1", recipe_id: "recipe_1", base_model: "TinyLlama/TinyLlama-1.1B-Chat-v1.0", method: "qlora", adapter_path: "/tmp/cand_1", dataset_version_id: "trainset_1", created_at: "2026-08-30T00:00:00Z" },
  ],
  "/api/v1/atlas/foundry/training-datasets": [
    { version_id: "trainset_1", created_at: "2026-08-29T00:00:00Z", source_run_count: 12, excluded_count: 2, train_count: 8, validation_count: 1, test_count: 1, content_hash: "b".repeat(64) },
  ],
  "/api/v1/atlas/foundry/preference-datasets": [
    { version_id: "prefset_1", created_at: "2026-08-29T00:00:00Z", source_count: 4, excluded_count: 0, train_count: 3, validation_count: 1, test_count: 0, content_hash: "c".repeat(64) },
  ],
  "/api/v1/atlas/foundry/jobs": [
    { job_id: "job_1", recipe_id: "recipe_1", backend: "soup", state: "completed", resource_lease_id: null, process_id: null, workspace_path: "/tmp/job_1", error: null, started_at: "2026-08-29T01:00:00Z", completed_at: "2026-08-29T02:00:00Z", created_at: "2026-08-29T00:30:00Z", updated_at: "2026-08-29T02:00:00Z" },
  ],
  "/api/v1/atlas/adapters/capabilities": [
    { adapter: "atlas-sql", can_load: false, can_unload: false, can_hot_swap: false, memory_cost_mb: null, compatible_base_models: [], detail: "No adapter runtime is wired up yet." },
  ],
};

function stubFetch(responses: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn(async (input: string | URL, init?: RequestInit) => {
    const path = String(input);
    if (init?.method === "POST") {
      for (const [suffix, body] of Object.entries(responses)) {
        if (path.split("?")[0]?.endsWith(suffix)) return json(body, suffix.endsWith("training-datasets") || suffix.endsWith("preference-datasets") ? 201 : 200);
      }
      return json({}, 200);
    }
    for (const [suffix, body] of Object.entries(responses)) {
      if (path.endsWith(suffix)) return json(body);
    }
    return json(null, 404);
  }));
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("Evolution workspace", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders honest empty states when no candidate has ever trained or promoted", async () => {
    stubFetch(emptyResponses);
    render(<EvolutionWorkspace />);
    await waitFor(() => expect(screen.getByText(/No candidate has ever been promoted/)).toBeInTheDocument());
    expect(screen.getByText(/No candidate has completed training yet/)).toBeInTheDocument();
    expect(screen.getAllByText(/No version has been built yet\./).length).toBe(2);
    expect(screen.getByText(/No training job is queued or running/)).toBeInTheDocument();
    expect(screen.getByText(/No promotion or rollback has ever occurred/)).toBeInTheDocument();
    expect(screen.getByText("soup · unavailable")).toBeInTheDocument();
  });

  it("renders real durable state once candidates, datasets, jobs, and a promotion exist", async () => {
    stubFetch(populatedResponses);
    render(<EvolutionWorkspace />);
    await waitFor(() => expect(screen.getAllByText("cand_1").length).toBeGreaterThan(0));
    expect(screen.getByText("trainset_1")).toBeInTheDocument();
    expect(screen.getByText("prefset_1")).toBeInTheDocument();
    expect(screen.getByText("soup · ready")).toBeInTheDocument();
    expect(screen.getByText("atlas-sql")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Roll back to previous candidate" })).toBeDisabled();
  });

  it("builds a training dataset version through the API", async () => {
    stubFetch(emptyResponses);
    render(<EvolutionWorkspace />);
    await waitFor(() => expect(screen.getByText(/No candidate has ever been promoted/)).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole("button", { name: "Build from current history" })[0]!);
    await waitFor(() => expect(window.fetch).toHaveBeenCalled());
  });
});
