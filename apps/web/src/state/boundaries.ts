import type { MigrationState } from "@prism/api-contracts";

/** Server state belongs to the transport/cache adapter, never a screen component. */
export interface PlatformServerState {
  migrationStates: readonly MigrationState[];
  refreshedAt: string | null;
}

/** Workspace state is durable navigation/context, separate from fetched server records. */
export interface WorkspaceState {
  activeDatasetId: string | null;
  activeWorkspace: string | null;
}

/** Ephemeral UI state must not leak into session or analytical contracts. */
export interface UiState {
  isCommandPaletteOpen: boolean;
  activeDialog: string | null;
}
