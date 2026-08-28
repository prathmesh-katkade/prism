import { tokens } from "./tokens.js";

/** Renderer-agnostic primitive contracts keep web and desktop visual language aligned. */
export interface ActionPrimitive {
  label: string;
  disabled?: boolean;
  ariaLabel?: string;
}

export interface SurfacePrimitive {
  label: string;
  tone?: "default" | "elevated" | "danger";
}

export const focusRing = `0 0 0 3px ${tokens.color.focus}`;
