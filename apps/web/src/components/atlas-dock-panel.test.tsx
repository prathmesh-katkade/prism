import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AtlasDockPanel } from "./atlas-dock-panel";

const clarification = {
  question: "Which date order should PRISM use for 03/04/2026?",
  column: "ordered_at",
  choices: [
    { label: "Day first", parameters: { date_format: "%d/%m/%Y" } },
    { label: "Month first", parameters: { date_format: "%m/%d/%Y" } },
  ],
};
const operation = { operation: "convert_type", column: "ordered_at", target_type: "datetime" };
const preview = { operation: "convert_type", review_token: "review_1", source_revision: 0, affected_rows: 2,
  changed_rows_total: 2, exception_rows_total: 0, unresolved_values: ["03/04/2026"], warnings: [],
  affected_columns: ["ordered_at"], before_sample: [], after_sample: [] };
const response = { kind: "clean", provider: "ollama", explanation: "Convert dates after choosing an order.", evidence: [],
  clean_operation: operation, clean_preview: preview, clarification };

function panel(onReview = vi.fn(), revision = 0) {
  return <AtlasDockPanel datasetId="ds_1" datasetName="orders.csv" revision={revision} focusLabel="ordered_at"
    operation={null} column="ordered_at" parameters={null} onReview={onReview} />;
}

afterEach(() => { vi.restoreAllMocks(); window.localStorage.clear(); });

describe("Atlas Clean clarification", () => {
  it("re-previews a typed date choice before review, without applying anything", async () => {
    const onReview = vi.fn();
    const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
      if (String(input).endsWith("/workspace-proposals")) return new Response(JSON.stringify(response), { status: 200 });
      if (String(input).endsWith("/preview")) {
        const request = JSON.parse(String(init?.body)) as Record<string, unknown>;
        expect(request).toMatchObject({ ...operation, date_format: "%d/%m/%Y" });
        expect(request.review_token).toBeUndefined();
        return new Response(JSON.stringify({ ...preview, review_token: "review_2", unresolved_values: [], warnings: ["1 invalid value became missing."] }), { status: 200 });
      }
      throw new Error(`Unexpected request: ${input}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(panel(onReview));
    fireEvent.change(screen.getByLabelText("Ask Atlas"), { target: { value: "Convert the order dates" } });
    fireEvent.click(screen.getByRole("button", { name: "Ask Atlas" }));
    await waitFor(() => expect(screen.getByText(clarification.question)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Review in Step settings" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Day first" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Review in Step settings" })).toBeInTheDocument());
    expect(screen.getByText("1 invalid value became missing.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review in Step settings" }));
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({
      clean_operation: expect.objectContaining({ date_format: "%d/%m/%Y" }),
      clean_preview: expect.objectContaining({ review_token: "review_2" }),
    }));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/apply"))).toHaveLength(0);
  });

  it("drops malformed nested stored responses and never renders their content", () => {
    window.localStorage.setItem("atlas-dock:ds_1", JSON.stringify([
      { id: "bad", intent: "dates", revision: 0, status: "done", response: { ...response, clarification: { question: "bad", choices: [{ label: "run", parameters: "not-an-object" }] } } },
      { id: "good", intent: "dates", revision: 0, status: "done", response },
    ]));
    render(panel());
    expect(screen.getByText(clarification.question)).toBeInTheDocument();
    expect(screen.queryByText("bad")).not.toBeInTheDocument();
    expect(document.querySelectorAll(".atlas-dock-turns > li")).toHaveLength(1);
  });
});
