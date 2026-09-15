"use client";

/**
 * Ranks the same already-fetched Command Center data (recent runs, current
 * production trust status) for what genuinely needs a human's attention,
 * instead of making them notice it by reading every panel. Deliberately
 * narrow: only conditions the backend already computes and marks as bad
 * qualify --
 *
 *   - a blocked or verification-required guardrail decision on a recent run
 *     (`atlas_guardrails.py`'s real `GuardrailDecision.state`: "blocked" |
 *     "verification_required" | "checked" -- "checked" is the passing
 *     state and never appears here),
 *   - a run that actually failed (a real `run_failed` event),
 *   - the current production candidate having recorded operational
 *     certification critical failures.
 *
 * No score is invented, no dataset-quality heuristic runs here (Overview's
 * own per-column health already covers that inside Overview, where it's
 * anchored to the dataset the user is actually looking at). When nothing
 * qualifies the panel says so plainly rather than manufacturing something
 * to show -- silence is the correct output of a working attention system,
 * not evidence the system is broken.
 */
import type { AtlasProductionTrustStatus, AtlasRunResponse } from "@prism/api-contracts";
import { CopyInvestigationLink, guardrailDecisionFor } from "./atlas-run-activity";

export type AttentionItem = {
  id: string;
  severity: "critical" | "warning";
  summary: string;
  detail: string;
  runId?: string;
};

export function buildAttentionQueue(status: AtlasProductionTrustStatus | null, runs: AtlasRunResponse[]): AttentionItem[] {
  const items: AttentionItem[] = [];

  const criticalFailures = status?.latest_operational_cert_critical_failures ?? 0;
  if (criticalFailures > 0) {
    items.push({
      id: "opcert_critical",
      severity: "critical",
      summary: `${criticalFailures} critical operational certification failure${criticalFailures === 1 ? "" : "s"}`,
      detail: `The current production candidate has unresolved critical failures against policy ${status?.operational_cert_min_pass_rate != null ? `(min pass rate ${(status.operational_cert_min_pass_rate * 100).toFixed(0)}%)` : ""}.`,
    });
  }

  for (const run of runs) {
    const guardrail = guardrailDecisionFor(run);
    if (guardrail && guardrail.state !== "checked") {
      items.push({
        id: `${run.run_id}_guardrail`,
        severity: guardrail.state === "blocked" ? "critical" : "warning",
        summary: `Guardrail ${guardrail.state.replaceAll("_", " ")}: "${run.plan.objective}"`,
        detail: `Policy ${guardrail.policy_version}${guardrail.findings.length ? ` -- ${guardrail.findings.length} finding${guardrail.findings.length === 1 ? "" : "s"}` : ""}.`,
        runId: run.run_id,
      });
    }
    const failure = (run.events ?? []).find((event) => event.type === "run_failed");
    if (failure) {
      const detail = failure.payload && typeof failure.payload.detail === "string" ? failure.payload.detail : "Run failed.";
      items.push({ id: failure.event_id, severity: "critical", summary: `Run failed: "${run.plan.objective}"`, detail, runId: run.run_id });
    }
  }

  return items.sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "critical" ? -1 : 1));
}

export function AttentionPanel({ status, statusFailed, runs, runsFailed }: { status: AtlasProductionTrustStatus | null; statusFailed: boolean; runs: AtlasRunResponse[]; runsFailed: boolean }) {
  if (statusFailed && runsFailed) return null; // Both underlying sources already report failure elsewhere (Hero, Run activity) -- avoid a third redundant error card.
  const items = buildAttentionQueue(statusFailed ? null : status, runsFailed ? [] : runs);
  return (
    <section className={`acc-attention${items.length ? " has-items" : ""}`} aria-label="Atlas attention queue">
      {items.length === 0 ? (
        <p className="acc-attention-clear">Nothing needs attention right now.</p>
      ) : (
        <ol>
          {items.map((item) => (
            <li key={item.id} data-severity={item.severity}>
              <div className="acc-attention-row">
                <span className={`migration-chip ${item.severity === "critical" ? "unavailable" : "bridged"}`}>{item.severity}</span>
                <strong>{item.summary}</strong>
              </div>
              <p>{item.detail}</p>
              {item.runId ? <CopyInvestigationLink runId={item.runId} focusNodeId={null} /> : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
