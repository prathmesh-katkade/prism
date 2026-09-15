"use client";

/**
 * A single reverse-chronological ledger of Atlas's material autonomous
 * outcomes: a run starting (the declared goal), the guardrail policy
 * decision made against it, how it ended, and every production
 * promotion/rollback -- merged from data the Command Center already fetches
 * (`AtlasRunResponse.events`, `AtlasProductionPointer` history), so this
 * adds no new backend endpoint and no new fact. Deliberately excludes
 * per-step execution detail (STEP_STARTED/STEP_COMPLETED,
 * COUNCIL_CONCLUSION) -- that belongs to the per-run execution timeline
 * already shown by `atlas-run-activity`; an accountability ledger is for
 * "what did Atlas decide and conclude," not a duplicate of the tool log.
 */
import type { AtlasProductionPointer, AtlasRunResponse } from "@prism/api-contracts";
import { CopyInvestigationLink, guardrailDecisionFor } from "./atlas-run-activity";

export type AccountabilityEntry =
  | { id: string; at: string; kind: "run_started"; runId: string; summary: string }
  | { id: string; at: string; kind: "guardrail"; runId: string; state: string; policyVersion: string; decisionId: string }
  | { id: string; at: string; kind: "run_completed" | "run_failed" | "run_cancelled"; runId: string; summary: string }
  | { id: string; at: string; kind: "promotion" | "rollback"; candidateId: string; reason: string };

const TERMINAL_TYPES = new Set(["run_completed", "run_failed", "run_cancelled"]);

export function buildAccountabilityLedger(runs: AtlasRunResponse[], promotions: AtlasProductionPointer[]): AccountabilityEntry[] {
  const entries: AccountabilityEntry[] = [];

  for (const run of runs) {
    const events = run.events ?? [];
    const created = events.find((event) => event.type === "run_created");
    if (created) entries.push({ id: created.event_id, at: created.occurred_at, kind: "run_started", runId: run.run_id, summary: run.plan.objective });

    const planCreated = events.find((event) => event.type === "plan_created");
    const guardrail = guardrailDecisionFor(run);
    if (planCreated && guardrail) {
      entries.push({ id: `${planCreated.event_id}_guardrail`, at: planCreated.occurred_at, kind: "guardrail", runId: run.run_id, state: guardrail.state, policyVersion: guardrail.policy_version, decisionId: guardrail.decision_id });
    }

    const terminal = [...events].reverse().find((event) => TERMINAL_TYPES.has(event.type));
    if (terminal) {
      const payload = terminal.payload ?? {};
      const summary =
        terminal.type === "run_failed"
          ? typeof payload.detail === "string" ? payload.detail : "Run failed."
          : terminal.type === "run_cancelled"
            ? typeof payload.reason === "string" ? `Cancelled (${payload.reason.replaceAll("_", " ")})` : "Cancelled."
            : (run.answer ?? "Completed.");
      entries.push({ id: terminal.event_id, at: terminal.occurred_at, kind: terminal.type as "run_completed" | "run_failed" | "run_cancelled", runId: run.run_id, summary });
    }
  }

  for (const pointer of promotions) {
    entries.push({ id: pointer.event_id, at: pointer.promoted_at, kind: pointer.is_rollback ? "rollback" : "promotion", candidateId: pointer.candidate_id, reason: pointer.reason });
  }

  return entries.sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
}

const KIND_LABEL: Record<AccountabilityEntry["kind"], string> = {
  run_started: "Run started",
  guardrail: "Guardrail decision",
  run_completed: "Run completed",
  run_failed: "Run failed",
  run_cancelled: "Run cancelled",
  promotion: "Promoted to production",
  rollback: "Rolled back",
};

function toneFor(entry: AccountabilityEntry): string {
  switch (entry.kind) {
    case "run_failed":
    case "rollback":
      return "unavailable";
    case "guardrail":
      return entry.state === "blocked" ? "unavailable" : entry.state === "verification_required" ? "bridged" : "ready";
    case "run_completed":
    case "promotion":
      return "native";
    default:
      return "legacy";
  }
}

function detailFor(entry: AccountabilityEntry): string {
  switch (entry.kind) {
    case "run_started":
      return entry.summary;
    case "guardrail":
      return `${entry.state.replaceAll("_", " ")} · policy ${entry.policyVersion}`;
    case "run_completed":
    case "run_failed":
    case "run_cancelled":
      return entry.summary;
    case "promotion":
    case "rollback":
      return `${entry.candidateId} · ${entry.reason}`;
  }
}

export function AccountabilityPanel({ runs, failed, promotions }: { runs: AtlasRunResponse[]; failed: boolean; promotions: AtlasProductionPointer[] }) {
  if (failed) {
    return (
      <article className="acc-panel acc-panel-wide">
        <h2>Accountability</h2>
        <p className="acc-empty">Could not build an accountability ledger -- the Atlas run history endpoint is unreachable.</p>
      </article>
    );
  }
  const entries = buildAccountabilityLedger(runs, promotions);
  return (
    <article className="acc-panel acc-panel-wide">
      <h2>Accountability</h2>
      <p className="acc-cortex-caption">
        Every material autonomous outcome from the recent runs and promotion history above, in one place: a run starting, its guardrail decision, how it ended, and every production promotion or rollback. Nothing here is inferred -- each row is a durable, timestamped record.
      </p>
      {entries.length === 0 ? (
        <p className="acc-empty">No recorded runs or promotions yet.</p>
      ) : (
        <ol className="acc-ledger">
          {entries.map((entry) => (
            <li key={entry.id}>
              <div className="acc-ledger-row">
                <span className={`migration-chip ${toneFor(entry)}`}>{KIND_LABEL[entry.kind]}</span>
                <time dateTime={entry.at}>{new Date(entry.at).toLocaleString()}</time>
              </div>
              <p>{detailFor(entry)}</p>
              {"runId" in entry ? <CopyInvestigationLink runId={entry.runId} focusNodeId={null} /> : null}
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}
