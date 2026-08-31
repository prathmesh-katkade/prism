import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvidenceInspector } from "./evidence-inspector";

const dataset = { dataset_id: "ds_1", revision: 0, source_fingerprint: "a".repeat(64) };

function analyticalObject(overrides: Record<string, unknown> = {}) {
  return {
    object_id: "stats_abc123",
    kind: "analysis",
    lifecycle: "completed",
    schema_version: "v1",
    payload: {},
    provenance: {
      dataset,
      parent_refs: [],
      warnings: [],
      evidence_refs: [],
      reproducibility: { kind: "statistical_test", producer: { service: "stats", version: "1" }, test: "pearson", columns: ["x", "y"], parameters: { alpha: 0.05 } },
      created_at: "2026-08-31T00:00:00Z",
    },
    ...overrides,
  };
}

const freshness = { state: "current", freshness_known: true, active_revision: 0, active_fingerprint: dataset.source_fingerprint, reason: "This is the exact dataset revision and content currently active for this dataset.", reason_code: "matches_active_identity" };

afterEach(() => vi.restoreAllMocks());

describe("Evidence inspector", () => {
  it("shows identity, freshness, and parameters for a selected object", async () => {
    const object = analyticalObject();
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/freshness")) return json(freshness);
      if (path.includes("/parents")) return json([]);
      if (path.includes("/children")) return json([]);
      return json(object);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<EvidenceInspector objectId="stats_abc123" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Statistical analysis" })).toBeInTheDocument());
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.getByText(/exact dataset revision/)).toBeInTheDocument();
    expect(screen.getByText("pearson")).toBeInTheDocument();
    expect(screen.getByText("alpha")).toBeInTheDocument();
    expect(screen.getByText("No upstream dependency recorded — this is a root object.")).toBeInTheDocument();
  });

  it("distinguishes stale from current with text, not color alone", async () => {
    const staleFreshness = { ...freshness, state: "stale", reason: "This result was produced from revision 0, which is no longer the active dataset state (revision 1 is now active)." };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/freshness")) return json(staleFreshness);
      if (path.includes("/parents")) return json([]);
      if (path.includes("/children")) return json([]);
      return json(analyticalObject());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<EvidenceInspector objectId="stats_abc123" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Stale")).toBeInTheDocument());
    expect(screen.getByText(/no longer the active dataset state/)).toBeInTheDocument();
  });

  it("navigates to a parent object and supports going back", async () => {
    const child = analyticalObject({ object_id: "stats_abc123" });
    const parent = analyticalObject({ object_id: "dsrev_ds_1_r0_aaaa", kind: "dataset_revision" });
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/freshness")) return json(freshness);
      if (path.includes("stats_abc123/parents")) return json([parent]);
      if (path.includes("stats_abc123/children")) return json([]);
      if (path.includes("dsrev_ds_1_r0_aaaa/parents")) return json([]);
      if (path.includes("dsrev_ds_1_r0_aaaa/children")) return json([child]);
      if (path.includes("dsrev_ds_1_r0_aaaa")) return json(parent);
      return json(child);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<EvidenceInspector objectId="stats_abc123" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Statistical analysis" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Dataset revision/ }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Dataset revision" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /Back/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Back/ }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Statistical analysis" })).toBeInTheDocument());
  });

  it("shows a clear message for an object that cannot be found, without crashing", async () => {
    const fetchMock = vi.fn(async () => new Response(null, { status: 404 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<EvidenceInspector objectId="does-not-exist" onClose={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("This analytical object could not be found."));
  });

  it("reproduces an object on current data and offers to view the new result", async () => {
    const object = analyticalObject();
    const newObject = analyticalObject({ object_id: "stats_new456" });
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/rerun")) {
        return json({ outcome: "created", original_object_id: "stats_abc123", mode: "current_revision", new_object: newObject, detail: "Reproduced as a new analysis object (stats_new456); the original object is unchanged." });
      }
      if (path.includes("/freshness")) return json(freshness);
      if (path.includes("/parents")) return json([]);
      if (path.includes("/children")) return json([]);
      if (path.includes("stats_new456")) return json(newObject);
      return json(object);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<EvidenceInspector objectId="stats_abc123" onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Statistical analysis" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Rerun on current data" }));

    await waitFor(() => expect(screen.getByText("New object created")).toBeInTheDocument());
    expect(screen.getByText(/the original object is unchanged/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "View new result" })).toBeInTheDocument();
  });

  it("shows a clear blocked message when a rerun is unsupported", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/rerun")) {
        return json({ outcome: "unsupported", original_object_id: "stats_abc123", mode: "current_revision", new_object: null, detail: "Rerun is not supported for dataset_revision objects." });
      }
      if (path.includes("/freshness")) return json(freshness);
      if (path.includes("/parents")) return json([]);
      if (path.includes("/children")) return json([]);
      return json(analyticalObject());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<EvidenceInspector objectId="stats_abc123" onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Statistical analysis" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Rerun on current data" }));

    await waitFor(() => expect(screen.getByText("Rerun not supported for this object")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent("Rerun is not supported for dataset_revision objects.");
  });

  it("calls onClose from the close button", async () => {
    const onClose = vi.fn();
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/freshness")) return json(freshness);
      if (path.includes("/parents")) return json([]);
      if (path.includes("/children")) return json([]);
      return json(analyticalObject());
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<EvidenceInspector objectId="stats_abc123" onClose={onClose} />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Statistical analysis" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Hide inspector" }));
    expect(onClose).toHaveBeenCalled();
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
