/** Shared semantic references. CSS owns theme values. */
export const tokens = {
  color: {
    canvas: "var(--prism-canvas)", surface: "var(--prism-surface)", raised: "var(--prism-raised)",
    text: "var(--prism-text)", muted: "var(--prism-muted)", border: "var(--prism-border)",
    focus: "var(--prism-focus)", selection: "var(--prism-selection)",
    completed: "var(--prism-completed)", blocked: "var(--prism-blocked)",
    running: "var(--prism-running)", recorded: "var(--prism-recorded)"
  },
  font: { sans: "var(--prism-font-sans)", mono: "var(--prism-font-mono)" },
  space: { 1: "var(--prism-space-1)", 2: "var(--prism-space-2)", 3: "var(--prism-space-3)", 4: "var(--prism-space-4)", 6: "var(--prism-space-6)", 8: "var(--prism-space-8)" },
  radius: { control: "var(--prism-radius-control)", panel: "var(--prism-radius-panel)" },
  border: { hairline: "var(--prism-border-hairline)", emphasis: "var(--prism-border-emphasis)" },
  density: { compactRow: "var(--prism-compact-row)", standardRow: "var(--prism-standard-row)" },
  motion: { feedback: "var(--prism-motion-feedback)", handoff: "var(--prism-motion-handoff)" }
} as const;

export type PrismTokens = typeof tokens;
