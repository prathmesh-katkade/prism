/** Typed CSS-variable references to the canonical values in tokens.css. */
export const tokens = {
  color: {
    canvas: "var(--atlas-color-canvas)",
    surface: "var(--atlas-color-surface)",
    surfaceRaised: "var(--atlas-color-surface-raised)",
    surfaceMuted: "var(--atlas-color-surface-muted)",
    border: "var(--atlas-color-border)",
    borderSubtle: "var(--atlas-color-border-subtle)",
    textPrimary: "var(--atlas-color-text-primary)",
    textSecondary: "var(--atlas-color-text-secondary)",
    textMuted: "var(--atlas-color-text-muted)",
    completed: "var(--atlas-color-completed)",
    blocked: "var(--atlas-color-blocked)",
    running: "var(--atlas-color-running)",
    recorded: "var(--atlas-color-recorded)",
    focus: "var(--atlas-color-focus)"
  },
  type: {
    display: "var(--atlas-type-display)",
    section: "var(--atlas-type-section)",
    body: "var(--atlas-type-body)",
    caption: "var(--atlas-type-caption)",
    monoData: "var(--atlas-type-mono-data)",
    sans: "var(--atlas-font-sans)",
    editorial: "var(--atlas-font-editorial)",
    mono: "var(--atlas-font-mono)"
  },
  space: {
    0: "var(--atlas-space-0)",
    1: "var(--atlas-space-1)",
    2: "var(--atlas-space-2)",
    3: "var(--atlas-space-3)",
    4: "var(--atlas-space-4)",
    6: "var(--atlas-space-6)",
    8: "var(--atlas-space-8)",
    10: "var(--atlas-space-10)",
    12: "var(--atlas-space-12)"
  },
  radius: {
    none: "var(--atlas-radius-none)",
    control: "var(--atlas-radius-control)",
    panel: "var(--atlas-radius-panel)",
    overlay: "var(--atlas-radius-overlay)"
  },
  border: {
    hairline: "var(--atlas-border-hairline)",
    emphasis: "var(--atlas-border-emphasis)",
    focus: "var(--atlas-border-focus)"
  },
  density: {
    compactRow: "var(--atlas-density-compact-row)",
    standardRow: "var(--atlas-density-standard-row)",
    relatedGap: "var(--atlas-density-related-gap)",
    sectionGap: "var(--atlas-density-section-gap)"
  }
} as const;

export type PrismTokens = typeof tokens;
export type PrismTokenColor = keyof typeof tokens.color;
export type PrismTokenType = keyof typeof tokens.type;


