import { describe, expect, it } from "vitest";
import { buildAtlasHistoryLink, parseAtlasHistoryQuery } from "./atlas-history-link";

describe("atlas history deep-link contract", () => {
  it("is inert -- returns no run/focus -- when atlas_panel=history is absent, so every existing dataset_id/run_id link keeps its current behavior", () => {
    expect(parseAtlasHistoryQuery("?dataset_id=ds_1&run_id=atlas_1")).toEqual({ runId: null, focusId: null });
    expect(parseAtlasHistoryQuery("")).toEqual({ runId: null, focusId: null });
  });

  it("is inert when atlas_panel=history is present but run_id is missing -- never a half-specified history target", () => {
    expect(parseAtlasHistoryQuery("?atlas_panel=history&atlas_focus=step:profile")).toEqual({ runId: null, focusId: null });
  });

  it("parses a real history deep link, with focus optional", () => {
    expect(parseAtlasHistoryQuery("?atlas_panel=history&run_id=atlas_1")).toEqual({ runId: "atlas_1", focusId: null });
    expect(parseAtlasHistoryQuery("?dataset_id=ds_1&atlas_panel=history&run_id=atlas_1&atlas_focus=step:profile")).toEqual({
      runId: "atlas_1",
      focusId: "step:profile",
    });
  });

  it("ignores an unrecognized atlas_panel value rather than guessing at intent", () => {
    expect(parseAtlasHistoryQuery("?atlas_panel=live&run_id=atlas_1")).toEqual({ runId: null, focusId: null });
  });

  it("builds a shareable link that sets run_id/atlas_panel/atlas_focus while preserving other existing query params", () => {
    const link = buildAtlasHistoryLink("https://prism.example/app?dataset_id=ds_1", "atlas_1", "step:profile");
    const url = new URL(link);
    expect(url.searchParams.get("dataset_id")).toBe("ds_1");
    expect(url.searchParams.get("run_id")).toBe("atlas_1");
    expect(url.searchParams.get("atlas_panel")).toBe("history");
    expect(url.searchParams.get("atlas_focus")).toBe("step:profile");
  });

  it("omits atlas_focus entirely when no focus is selected, rather than embedding an empty value", () => {
    const link = buildAtlasHistoryLink("https://prism.example/app", "atlas_1", null);
    const url = new URL(link);
    expect(url.searchParams.has("atlas_focus")).toBe(false);
  });

  it("overwrites a stale run_id/atlas_focus already on the page rather than duplicating params", () => {
    const link = buildAtlasHistoryLink("https://prism.example/app?run_id=old_run&atlas_focus=old_focus", "atlas_new", "step:new");
    const url = new URL(link);
    expect(url.searchParams.getAll("run_id")).toEqual(["atlas_new"]);
    expect(url.searchParams.getAll("atlas_focus")).toEqual(["step:new"]);
  });
});
