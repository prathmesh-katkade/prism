"use client";

/**
 * The genuine, narrow kernel of "Mission Control": which of the Command
 * Center's already-fetched recent runs are actually in flight right now
 * (`plan.state` is the real `AtlasPlanState` "draft" or "running", never a
 * status this module invents), so a user with more than one Atlas
 * investigation going can see and jump between them. This does not attempt
 * independent priorities, dependencies, or resource scheduling -- the
 * backend has no such data to show honestly (concurrency is real --
 * `atlas_run_admission.py` runs up to 8 concurrent runs on a real thread
 * pool -- but nothing ranks or schedules them beyond FIFO admission).
 * Renders nothing at all when no mission is active: a permanent "0 active"
 * chip would be exactly the dead ambient chrome the product explicitly
 * avoids elsewhere.
 */
import type { AtlasRunResponse } from "@prism/api-contracts";
import { CopyInvestigationLink } from "./atlas-run-activity";

export type ActiveMission = { run: AtlasRunResponse; state: "draft" | "running" };

export function filterActiveMissions(runs: AtlasRunResponse[]): ActiveMission[] {
  const missions: ActiveMission[] = [];
  for (const run of runs) {
    if (run.plan.state === "draft" || run.plan.state === "running") missions.push({ run, state: run.plan.state });
  }
  return missions;
}

export function MissionControlPanel({ runs, failed }: { runs: AtlasRunResponse[]; failed: boolean }) {
  if (failed) return null; // Run activity's own panel already reports this failure -- avoid a duplicate error card.
  const missions = filterActiveMissions(runs);
  if (missions.length === 0) return null;
  return (
    <section className="acc-missions" aria-label="Atlas active missions">
      <span className="eyebrow">
        ATLAS · {missions.length} ACTIVE MISSION{missions.length === 1 ? "" : "S"}
      </span>
      <ul>
        {missions.map(({ run, state }) => (
          <li key={run.run_id}>
            <div className="acc-missions-row">
              <span className={`migration-chip ${state === "running" ? "bridged" : "legacy"}`}>{state}</span>
              <strong>{run.plan.objective}</strong>
            </div>
            <CopyInvestigationLink runId={run.run_id} focusNodeId={null} />
          </li>
        ))}
      </ul>
    </section>
  );
}
