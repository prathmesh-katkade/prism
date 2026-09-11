import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HistoryWorkspace } from "./history-workspace";

afterEach(() => vi.restoreAllMocks());

describe("History workspace", () => {
  it("filters durable history and opens the selected immutable evidence object", async () => {
    const object = { object_id: "analysis_1", kind: "analysis", lifecycle: "completed", schema_version: "v1", payload: {}, provenance: { dataset: { dataset_id: "ds_1", revision: 0, source_fingerprint: "a".repeat(32) }, parent_refs: [], warnings: [], evidence_refs: [], reproducibility: { kind: "generic", producer: { service: "stats", version: "1" }, operation: "pearson", parameters: {} }, created_at: "2026-09-01T00:00:00Z" } };
    const fetchMock = vi.fn(async (input: string | URL) => String(input).includes("freshness")
      ? json({ state: "current", freshness_known: true, active_revision: 0, active_fingerprint: "a".repeat(32), reason: "Current", reason_code: "current" })
      : json([object]));
    const onSelectContext = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<HistoryWorkspace onSelectContext={onSelectContext} />);

    await waitFor(() => expect(screen.getByText("Analytical history")).toBeInTheDocument());
    fireEvent.change(screen.getByRole("textbox", { name: "Search analytical history" }), { target: { value: "analysis" } });
    fireEvent.click(screen.getByRole("button", { name: "Inspect" }));
    expect(onSelectContext).toHaveBeenCalledWith(expect.objectContaining({ analyticalObjectId: "analysis_1" }));
  });
});

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}
