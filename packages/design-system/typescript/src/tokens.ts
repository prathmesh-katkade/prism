/** Phase 1 semantic tokens. Components must consume tokens, not raw product colors. */
export const tokens = {
  color: {
    canvas: "#07111F",
    surface: "#0C1B2D",
    text: "#F4F8FC",
    mutedText: "#AFC0D3",
    focus: "#38BDF8",
    danger: "#FB7185"
  },
  space: { 1: "0.25rem", 2: "0.5rem", 3: "0.75rem", 4: "1rem", 6: "1.5rem", 8: "2rem" },
  radius: { control: "0.5rem", panel: "0.75rem" }
} as const;

export type PrismTokens = typeof tokens;
