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
  it("labels an explanation without a proposed edit honestly", async () => {
    const answer = { kind: "clean", provider: "ollama", explanation: "Review blank regions first.", evidence: [] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(answer), { status: 200 })));
    render(panel());
    fireEvent.click(screen.getByRole("button", { name: "What should I review first?" }));
    await waitFor(() => expect(screen.getByText(answer.explanation)).toBeInTheDocument());
    expect(screen.getByText("Atlas explained (local model)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review in Step settings" })).not.toBeInTheDocument();
  });

  it("names the actual local model that answered, when the backend reports one", async () => {
    // This lane picks a model from whatever is actually installed when none
    // is explicitly configured - the analyst must be able to see which one
    // really ran, not just an unlabeled "local model".
    const answer = { kind: "clean", provider: "ollama", model: "qwen2.5:3b", explanation: "Review blank regions first.", evidence: [] };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(answer), { status: 200 })));
    render(panel());
    fireEvent.click(screen.getByRole("button", { name: "What should I review first?" }));
    await waitFor(() => expect(screen.getByText(answer.explanation)).toBeInTheDocument());
    expect(screen.getByText("Atlas explained (qwen2.5:3b)")).toBeInTheDocument();
  });

  it("keeps verbose source provenance behind an inspectable disclosure and offers retry", async () => {
    const unavailable = { kind: "clean", provider: "unavailable", explanation: "The selected local model is not installed.", evidence: ["Source ds_1, revision 0, fingerprint abc."] };
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(unavailable), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(panel());
    fireEvent.click(screen.getByRole("button", { name: "What should I review first?" }));
    await waitFor(() => expect(screen.getByText(unavailable.explanation)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "What should I review first?" })).not.toBeInTheDocument();
    expect(screen.getByText("Inspect source evidence and provenance")).toBeInTheDocument();
    expect(screen.getByText(unavailable.evidence[0]!).closest("details")).not.toHaveAttribute("open");
    fireEvent.click(screen.getByRole("button", { name: "Retry with local model" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

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
    expect(screen.getByRole("region", { name: "Preview checks" })).toHaveTextContent("3 / 4 clear");
    expect(screen.getByRole("region", { name: "Preview checks" })).toHaveTextContent("Analyst decision required");
    expect(screen.queryByRole("button", { name: "Review in Step settings" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Day first" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Review in Step settings" })).toBeInTheDocument());
    expect(screen.getByText("1 invalid value became missing.")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Preview checks" })).toHaveTextContent("3 / 4 clear");
    fireEvent.click(screen.getByRole("button", { name: "Review in Step settings" }));
    expect(onReview).toHaveBeenCalledWith(expect.objectContaining({
      clean_operation: expect.objectContaining({ date_format: "%d/%m/%Y" }),
      clean_preview: expect.objectContaining({ review_token: "review_2" }),
    }));
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/apply"))).toHaveLength(0);
  });

  it("shows next-step quick actions after a turn completes, and each submits its own real intent", async () => {
    const first = { kind: "clean", provider: "ollama", explanation: "Review blank regions first.", evidence: [] };
    const second = { kind: "clean", provider: "ollama", explanation: "Before: BENGALURU. After: Bengaluru.", evidence: [] };
    const fetchMock = vi.fn(async (_input: string | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { intent: string };
      const payload = fetchMock.mock.calls.length === 1 ? first : second;
      expect(body.intent).toBe(fetchMock.mock.calls.length === 1 ? "What should I review first?" : "What changed between before and after for this step?");
      return new Response(JSON.stringify(payload), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(panel());
    expect(screen.queryByText("Suggest next steps")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "What should I review first?" }));
    await waitFor(() => expect(screen.getByText(first.explanation)).toBeInTheDocument());
    expect(screen.getByText("Suggest next steps")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain this step" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suggest what to clean up next" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare before and after" }));
    await waitFor(() => expect(screen.getByText(second.explanation)).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("hides the next-step quick actions while a request is pending, and keeps conversation context across them", async () => {
    let resolveSecond: ((value: Response) => void) | undefined;
    const first = { kind: "clean", provider: "ollama", explanation: "Review blank regions first.", evidence: [] };
    const fetchMock = vi.fn(async (_input: string | URL, init?: RequestInit) => {
      if (fetchMock.mock.calls.length === 1) return new Response(JSON.stringify(first), { status: 200 });
      const body = JSON.parse(String(init?.body)) as { history?: Array<{ intent: string }> };
      // The follow-up must carry the prior turn as real context, not a blank slate.
      expect(body.history).toEqual([{ intent: "What should I review first?", explanation: first.explanation }]);
      return new Promise<Response>((resolve) => { resolveSecond = resolve; });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(panel());
    fireEvent.click(screen.getByRole("button", { name: "What should I review first?" }));
    await waitFor(() => expect(screen.getByText(first.explanation)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Explain this step" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument());
    expect(screen.queryByText("Suggest next steps")).not.toBeInTheDocument();
    resolveSecond!(new Response(JSON.stringify({ kind: "clean", provider: "ollama", explanation: "The current step maps region spellings.", evidence: [] }), { status: 200 }));
    await waitFor(() => expect(screen.getByText("Suggest next steps")).toBeInTheDocument());
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
