import type { MigrationState } from "@prism/api-contracts";

export type ShellStatus = "empty" | "project-loaded" | "loading" | "degraded" | "error" | "migration-bridge";
export type ThemeMode = "dark" | "light";
export type Density = "comfortable" | "compact";
export type PanelId = "rail" | "inspector" | "atlas";

export interface WorkspaceTab {
  id: string;
  label: string;
  kind: "home" | "bridge" | "overview" | "sql-lab" | "ai-analyst" | "clean" | "visualize" | "atlas";
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
  { workflow: "stats", channel: "legacy", legacy_reference: "legacy://stats", parity_required: true },
  { workflow: "forecasting", channel: "legacy", legacy_reference: "legacy://forecasting", parity_required: true },
  { workflow: "ml", channel: "legacy", legacy_reference: "legacy://ml", parity_required: true }
];

export function migrationPresentation(migration: MigrationState): "native" | "bridged" | "legacy" {
  if (migration.channel === "enabled") return "native";
  if (migration.channel === "shadow") return "bridged";
  return "legacy";
}
