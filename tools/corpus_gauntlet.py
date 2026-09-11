"""
Corpus Gauntlet — runs Prism's real engine, end to end, against every
dataset downloaded into corpus_cache/ by tools/corpus.py. Not a mock, not
a smoke test: the same data_engine / hellmode / autocleaner / visualization
/ report_writer / ai_analyst functions the Streamlit app itself calls.

Eight stages per dataset:
  1. load          — data_engine.load_data() (encoding fallback, Excel/CSV)
  2. scan          — column type detection + quality report + Hell Mode sweep
  3. auto_clean    — Auto Cleaner's scan -> plan -> execute (SAFE actions only)
  4. invariants    — sanity checks on the cleaned frame (see _check_invariants)
  5. dashboard     — visualization.auto_generate_charts() (no AI required)
  6. report        — Report Writer's PDF + HTML export (the fpdf2 multi_cell
                      crash class lives here — see modules/report_writer.py)
  7. ai_questions  — 2 fixed questions through ai_analyst.ask_and_execute();
                      SKIPPED (not failed) if no Gemini key is configured
  8. export        — cleaning.export_script() produces valid Python; a CSV
                      round-trip preserves row count

A stage failure is caught, logged with its traceback, and the run moves on
to the next stage for that dataset, then the next dataset — nothing here
is allowed to take down the whole corpus run. That's the entire point:
this script's job is to find every way Prism breaks on real data, not to
stop at the first one.

Run with:
  python tools/corpus_gauntlet.py            # full corpus
  python tools/corpus_gauntlet.py --quick     # nightmare.csv + the 5
                                                 regression-locked datasets
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from modules import (  # noqa: E402
    ai_analyst,
    autocleaner,
    cleaning,
    data_engine,
    report_writer,
    visualization,
)

TOOLS_DIR = Path(__file__).resolve().parent
CACHE_DIR = REPO_ROOT / "corpus_cache"
MANIFEST_PATH = CACHE_DIR / "manifest.json"
REGISTRY_PATH = TOOLS_DIR / "corpus_registry.json"
REPORT_PATH = REPO_ROOT / "corpus_report.md"
HARDENING_PATH = REPO_ROOT / "HARDENING.md"

STAGES = ["load", "scan", "auto_clean", "invariants", "dashboard", "report", "ai_questions", "export"]

# The 5 most instructive datasets (by name, from corpus_registry.json) that
# --quick locks in as a fast regression check, alongside samples/hell's
# nightmare-style file. Populated once the full corpus run identifies which
# 5 actually taught the parser the most — see tools/corpus_registry.json's
# "regression_lock" list.
_NIGHTMARE_SAMPLE = REPO_ROOT / "samples" / "hell" / "house_prices_ames_messy.csv"


class _LocalFileUpload(io.BytesIO):
    """Adapts a plain file on disk to the {.name, read(), seek()} shape
    data_engine.load_data() expects from a Streamlit UploadedFile — the
    same trick used by ai_analyst's own eval harness.
    """

    def __init__(self, path: Path):
        super().__init__(path.read_bytes())
        self.name = path.name


def _stage_result(status: str, detail: str = "", error: Optional[str] = None) -> dict:
    return {"status": status, "detail": detail, "error": error}


def _check_invariants(before: pd.DataFrame, after: pd.DataFrame, before_types: dict, after_types: dict) -> dict:
    """Sanity checks Auto Cleaner must never violate, on any input.
    Returns a stage result — 'failed' if any invariant is broken.
    """
    problems = []
    if len(after) > len(before):
        problems.append(f"row count grew ({len(before)} -> {len(after)}) — cleaning must never add rows")
    if after.shape[1] == 0:
        problems.append("all columns were dropped")
    newly_all_null = [
        c for c in after.columns
        if c in before.columns and after[c].isna().all() and not before[c].isna().all()
    ]
    if newly_all_null:
        problems.append(f"column(s) became fully null that weren't before: {newly_all_null}")
    quality_after = data_engine.get_data_quality_report(after, after_types)
    health = data_engine.get_health_score(quality_after, after_types)
    if not (0 <= health <= 100):
        problems.append(f"health score out of range: {health}")

    if problems:
        return _stage_result("failed", error="; ".join(problems))
    return _stage_result("ok", detail=f"health={health}")


def _run_stages(path: Path, name: str) -> dict:
    stage_results: dict[str, dict] = {}
    t0 = time.time()

    # ---- Stage 1: load ----
    try:
        upload = _LocalFileUpload(path)
        df, load_error, warnings = data_engine.load_data(upload, max_rows=None)
        if load_error:
            stage_results["load"] = _stage_result("failed", error=load_error)
            return _finish(name, stage_results, t0)
        n_rows, n_cols = df.shape
        stage_results["load"] = _stage_result("ok", detail=f"{n_rows} rows x {n_cols} cols; warnings={warnings}")
    except Exception as e:
        stage_results["load"] = _stage_result("failed", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        return _finish(name, stage_results, t0)

    # ---- Stage 2: scan ----
    try:
        column_types = data_engine.detect_column_types(df)
        quality = data_engine.get_data_quality_report(df, column_types)
        health_before = data_engine.get_health_score(quality, column_types)
        scan_results = autocleaner.scan(df, column_types, quality)
        n_findings = sum(
            len(v) if isinstance(v, (list, dict)) else 1
            for k, v in scan_results.items() if k not in ("missing_by_column", "outliers")
        )
        stage_results["scan"] = _stage_result("ok", detail=f"health_before={health_before}, findings~{n_findings}")
    except Exception as e:
        stage_results["scan"] = _stage_result("failed", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        return _finish(name, stage_results, t0)

    # ---- Stage 3: auto_clean ----
    try:
        plan = autocleaner.build_plan(df, column_types, scan_results)
        cleaned_df, cleaned_types, log_entries, applied = autocleaner.execute_safe_actions(df, column_types, plan)
        review_count = sum(1 for a in plan if a["risk"] == "REVIEW")
        stage_results["auto_clean"] = _stage_result(
            "ok", detail=f"{applied} SAFE action(s) applied, {review_count} REVIEW action(s) flagged"
        )
    except Exception as e:
        stage_results["auto_clean"] = _stage_result("failed", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        cleaned_df, cleaned_types = df, column_types  # keep going with the uncleaned frame

    # ---- Stage 4: invariants ----
    try:
        stage_results["invariants"] = _check_invariants(df, cleaned_df, column_types, cleaned_types)
    except Exception as e:
        stage_results["invariants"] = _stage_result("failed", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

    # Scorecard-only (not a stage): health after cleaning, for the badge
    # table. Failing to compute this never fails the run — it's reporting,
    # not validation (invariants above already covers correctness).
    try:
        health_after = data_engine.get_health_score(
            data_engine.get_data_quality_report(cleaned_df, cleaned_types), cleaned_types
        )
    except Exception:
        health_after = None

    # ---- Stage 5: dashboard ----
    try:
        charts, top_corr = visualization.auto_generate_charts(cleaned_df, cleaned_types)
        stage_results["dashboard"] = _stage_result("ok", detail=f"{len(charts)} chart(s)")
    except Exception as e:
        stage_results["dashboard"] = _stage_result("failed", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
        charts, top_corr = {}, []

    # ---- Stage 6: report ----
    try:
        cleaned_quality = data_engine.get_data_quality_report(cleaned_df, cleaned_types)
        model = ai_analyst.get_model()
        content = report_writer.build_report_content(model, cleaned_df, cleaned_quality, cleaned_types, charts, top_corr)
        pdf_bytes = report_writer.generate_pdf_report(content, name)
        html_text = report_writer.generate_html_report(content, name)
        stage_results["report"] = _stage_result("ok", detail=f"pdf={len(pdf_bytes)}B html={len(html_text)}B")
    except Exception as e:
        stage_results["report"] = _stage_result("failed", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

    # ---- Stage 7: ai_questions ----
    try:
        model = ai_analyst.get_model()
        if model is None:
            stage_results["ai_questions"] = _stage_result("skipped", detail="no GEMINI_API_KEY configured")
        else:
            answers = []
            for q in ["How many rows and columns are in this dataset?", "What are the column names?"]:
                outcome = ai_analyst.ask_and_execute(model, cleaned_df, cleaned_types, q, [])
                if outcome["ask_error"] or outcome["error"]:
                    answers.append(f"FAIL[{q}]: {outcome['ask_error'] or outcome['error']}")
                else:
                    answers.append(f"OK[{q}]")
            failed = [a for a in answers if a.startswith("FAIL")]
            stage_results["ai_questions"] = (
                _stage_result("failed", error="; ".join(failed)) if failed else _stage_result("ok", detail="; ".join(answers))
            )
    except Exception as e:
        stage_results["ai_questions"] = _stage_result("failed", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

    # ---- Stage 8: export ----
    try:
        script = cleaning.export_script(log_entries, name)
        compile(script, "<export_script>", "exec")  # syntax-valid, not necessarily runnable without df/pd/np in scope
        buf = io.StringIO()
        cleaned_df.to_csv(buf, index=False)
        buf.seek(0)
        round_tripped = pd.read_csv(buf)
        if len(round_tripped) != len(cleaned_df):
            stage_results["export"] = _stage_result(
                "failed", error=f"CSV round-trip row count mismatch: {len(cleaned_df)} -> {len(round_tripped)}"
            )
        else:
            stage_results["export"] = _stage_result("ok", detail=f"{len(script)} char script, round-trip OK")
    except Exception as e:
        stage_results["export"] = _stage_result("failed", error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}")

    return _finish(
        name, stage_results, t0,
        health_before=locals().get("health_before"), health_after=locals().get("health_after"),
        n_rows=locals().get("n_rows"), n_cols=locals().get("n_cols"),
    )


def _finish(
    name: str, stage_results: dict, t0: float,
    health_before: Optional[int] = None, health_after: Optional[int] = None,
    n_rows: Optional[int] = None, n_cols: Optional[int] = None,
) -> dict:
    for stage in STAGES:
        stage_results.setdefault(stage, _stage_result("skipped", detail="not reached (earlier stage failed)"))
    return {
        "name": name,
        "runtime_seconds": round(time.time() - t0, 2),
        "health_before": health_before,
        "health_after": health_after,
        "n_rows": n_rows,
        "n_cols": n_cols,
        "stages": stage_results,
    }


def run_gauntlet(quick: bool = False) -> list[dict]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.exists() else []
    downloaded = [m for m in manifest if m["status"] == "ok"]

    targets: list[tuple[str, Path]] = []
    if quick:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        lock_names = set(registry.get("regression_lock", []))
        targets = [(m["name"], REPO_ROOT / m["path"]) for m in downloaded if m["name"] in lock_names]
        if _NIGHTMARE_SAMPLE.exists():
            targets.append(("nightmare (house_prices_ames_messy)", _NIGHTMARE_SAMPLE))
    else:
        targets = [(m["name"], REPO_ROOT / m["path"]) for m in downloaded]
        if _NIGHTMARE_SAMPLE.exists():
            targets.append(("nightmare (house_prices_ames_messy)", _NIGHTMARE_SAMPLE))

    if not targets:
        print("No downloaded datasets found — run `python tools/corpus.py` first.")
        return []

    results = []
    for name, path in targets:
        print(f"Running gauntlet on {name} ({path.name})...")
        try:
            result = _run_stages(path, name)
        except Exception as e:  # a bug in the runner itself must not kill the corpus loop either
            result = {
                "name": name, "runtime_seconds": 0, "health_before": None, "health_after": None,
                "n_rows": None, "n_cols": None,
                "stages": {s: _stage_result("failed", error=f"runner crashed: {e}") for s in STAGES},
            }
        results.append(result)
        n_ok = sum(1 for s in result["stages"].values() if s["status"] == "ok")
        print(f"  {n_ok}/{len(STAGES)} stages passed ({result['runtime_seconds']}s)")

    _write_report(results)
    if not quick:
        _write_scorecard(results)
    return results


SCORECARD_PATH = REPO_ROOT / "corpus_scorecard.json"


def _write_scorecard(results: list[dict]) -> None:
    """A leaner, badge-table-ready summary (one row per dataset) — the
    per-stage report above is for debugging failures, this is for the
    README's compatibility badge (see README's 'Battle-tested on real
    data' section, generated from this file)."""
    scorecard = [
        {
            "name": r["name"],
            "n_rows": r["n_rows"],
            "n_cols": r["n_cols"],
            "health_before": r["health_before"],
            "health_after": r["health_after"],
            "stages_passed": sum(1 for s in r["stages"].values() if s["status"] == "ok"),
            "stages_total": len(STAGES),
            "runtime_seconds": r["runtime_seconds"],
        }
        for r in results
    ]
    SCORECARD_PATH.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")


def _write_report(results: list[dict]) -> None:
    lines = ["# Prism — Corpus Gauntlet Report", "", f"{len(results)} dataset(s) run against {len(STAGES)} stages.", ""]
    lines.append("| Dataset | " + " | ".join(STAGES) + " | Runtime |")
    lines.append("|---|" + "---|" * len(STAGES) + "---|")
    status_icon = {"ok": "PASS", "failed": "FAIL", "skipped": "SKIP"}
    for r in results:
        cells = [status_icon[r["stages"][s]["status"]] for s in STAGES]
        lines.append(f"| {r['name']} | " + " | ".join(cells) + f" | {r['runtime_seconds']}s |")

    lines.append("")
    lines.append("## Failures in detail")
    any_failure = False
    for r in results:
        for stage in STAGES:
            sr = r["stages"][stage]
            if sr["status"] == "failed":
                any_failure = True
                lines.append(f"### {r['name']} — {stage}")
                lines.append(f"```\n{sr['error']}\n```")
    if not any_failure:
        lines.append("None — every dataset that reached a stage passed it.")

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    n_total_stage_runs = sum(1 for r in results for s in STAGES if r["stages"][s]["status"] != "skipped")
    n_passed = sum(1 for r in results for s in STAGES if r["stages"][s]["status"] == "ok")
    print(f"\n{n_passed}/{n_total_stage_runs} stage-runs passed — report: {REPORT_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Prism's engine against the real-world corpus.")
    parser.add_argument("--quick", action="store_true", help="Only run the regression-locked subset + nightmare.csv.")
    args = parser.parse_args()
    run_gauntlet(quick=args.quick)
