import type { MigrationState, ReleaseChannel } from "@prism/api-contracts";

export type FeatureFlag = "new-overview" | "new-sql-lab" | "new-ai-analyst";

const flagWorkflow: Record<FeatureFlag, string> = {
  "new-overview": "overview",
  "new-sql-lab": "sql-lab",
  "new-ai-analyst": "ai-analyst"
};

export function isFeatureAvailable(flag: FeatureFlag, migrations: readonly MigrationState[]): boolean {
  const migration = migrations.find((item) => item.workflow === flagWorkflow[flag]);
  return migration !== undefined && isVisible(migration.channel);
}

function isVisible(channel: ReleaseChannel): boolean {
  return channel === "enabled";
}
