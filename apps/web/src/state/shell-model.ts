import type { MigrationState } from "@prism/api-contracts";

export type ShellStatus = "empty" | "project-loaded" | "loading" | "degraded" | "error" | "migration-bridge";
export type ThemeMode = "dark" | "light";
export type Density = "comfortable" | "compact";
export type PanelId = "rail" | "inspector" | "atlas";

export interface WorkspaceTab {
  id: string;
  label: string;
  kind: "home" | "bridge" | "overview" | "sql-lab" | "ai-analyst" | "clean" | "visualize" | "stats" | "forecasting" | "ml" | "history" | "atlas";
  workflow?: string;
  closeable: boolean;
}

export interface PersistedLayout {
  theme: ThemeMode;
  density: Density;
  railCollapsed: boolean;
  railWidth: number;
  inspectorOpen: boolean;
  inspectorWidth: number;
  atlasExpanded: boolean;
  splitView: boolean;
}

export interface InspectorObjectState {
  objectId: string | null;
  label: string;
  type: "project" | "dataset" | "workflow" | "column" | "finding" | "none";
  state: "ready" | "legacy" | "bridged" | "native" | "unavailable";
  actions: readonly ContextAction[];
  metadata?: readonly string[];
  /** Phase 8E: when set, this is a real Phase 8 analytical-registry object id (not one
   * of the synthetic `objectId` values used above) - the shell renders the dedicated
   * Evidence Inspector for it instead of the generic context panel. */
  analyticalObjectId?: string;
}

export interface ContextAction {
  id: string;
  label: string;
  shortcut?: string;
  disabled?: boolean;
}

export const phaseTwoMigrations: readonly MigrationState[] = [
  { workflow: "overview", channel: "enabled", legacy_reference: "legacy://overview", parity_required: true },
  { workflow: "sql-lab", channel: "enabled", legacy_reference: "legacy://sql-lab", parity_required: true },
  { workflow: "ai-analyst", channel: "enabled", legacy_reference: "legacy://ai-analyst", parity_required: true },
  { workflow: "clean", channel: "enabled", legacy_reference: "legacy://clean", parity_required: true },
  { workflow: "visualize", channel: "enabled", legacy_reference: "legacy://visualize", parity_required: true },
  { workflow: "stats", channel: "enabled", legacy_reference: "modules/stats_lab.py", parity_required: true },
  { workflow: "forecasting", channel: "enabled", legacy_reference: "modules/forecasting.py", parity_required: true },
  { workflow: "ml", channel: "enabled", legacy_reference: "modules/mllab.py", parity_required: true }
];

export function migrationPresentation(migration: MigrationState): "native" | "bridged" | "legacy" {
  if (migration.channel === "enabled") return "native";
  if (migration.channel === "shadow") return "bridged";
  return "legacy";
}
