"use client";

/**
 * The data-tile Atlas mascot: a small stack of index cards with a face,
 * matching the approved reference (docs/clean-atlas-v1/references/01, 02).
 * One component, two sizes, four restrained poses tied to real states - it
 * never animates to suggest work that isn't happening, and never grows a
 * fifth pose "just because" one looks nice; each pose exists because a real
 * interaction state needs it (idle watching, working, presenting evidence,
 * waiting on the person).
 *
 * Reduced motion: this file adds no per-element media query because
 * prism.css already has a blanket `@media (prefers-reduced-motion:reduce)`
 * rule that zeroes every animation/transition duration site-wide - adding a
 * second, narrower guard here would be redundant, not more correct.
 */
export type AtlasPose = "idle" | "working" | "presenting" | "waiting";

export function AtlasCharacter({ pose = "idle", size = "small", className }: { pose?: AtlasPose; size?: "small" | "large"; className?: string }) {
  const box = size === "large" ? 96 : 28;
  return (
    <svg
      className={`atlas-character atlas-character-${size} atlas-character-${pose}${className ? ` ${className}` : ""}`}
      width={box} height={box} viewBox="0 0 96 96" role="img"
      aria-label={`Atlas, ${POSE_LABEL[pose]}`}
    >
      {/* Two trailing tiles give the "stack of cards" depth from the
          reference without needing a raster asset. */}
      <rect className="atlas-card atlas-card-back" x="20" y="14" width="56" height="64" rx="12" />
      <rect className="atlas-card atlas-card-mid" x="14" y="10" width="60" height="68" rx="12" />
      <rect className="atlas-card atlas-card-face" x="10" y="8" width="64" height="70" rx="13" />
      <FaceFeatures pose={pose} />
    </svg>
  );
}

const POSE_LABEL: Record<AtlasPose, string> = {
  idle: "watching",
  working: "working",
  presenting: "presenting evidence",
  waiting: "waiting for your input",
};

function FaceFeatures({ pose }: { pose: AtlasPose }) {
  if (pose === "working") {
    return <g className="atlas-face">
      {/* Eyes looking down at its own work, not at the person. */}
      <path d="M30 42 q6 -5 12 0" className="atlas-eye" />
      <path d="M54 42 q6 -5 12 0" className="atlas-eye" />
      <path d="M36 60 q6 4 12 0 q6 -4 12 0" className="atlas-mouth" />
      <g className="atlas-working-dots"><circle cx="34" cy="70" r="2.6" /><circle cx="42" cy="70" r="2.6" /><circle cx="50" cy="70" r="2.6" /></g>
    </g>;
  }
  if (pose === "presenting") {
    return <g className="atlas-face">
      <circle cx="36" cy="40" r="4" className="atlas-eye" />
      <circle cx="60" cy="40" r="4" className="atlas-eye" />
      <path d="M34 58 q10 8 20 0" className="atlas-mouth" />
      {/* A small held "evidence tile", echoing the reference's record card. */}
      <rect x="66" y="48" width="18" height="14" rx="2" className="atlas-evidence-chip" />
      <line x1="69" y1="52" x2="81" y2="52" className="atlas-evidence-line" />
      <line x1="69" y1="57" x2="77" y2="57" className="atlas-evidence-line" />
    </g>;
  }
  if (pose === "waiting") {
    return <g className="atlas-face">
      <circle cx="36" cy="40" r="4" className="atlas-eye" />
      <circle cx="60" cy="40" r="4" className="atlas-eye" />
      {/* One raised brow reads as an open, unresolved question. */}
      <path d="M30 30 q6 -4 12 0" className="atlas-brow" />
      <path d="M38 60 h12" className="atlas-mouth" />
    </g>;
  }
  return <g className="atlas-face">
    <circle cx="36" cy="40" r="4" className="atlas-eye" />
    <circle cx="60" cy="40" r="4" className="atlas-eye" />
    <path d="M34 56 q10 10 20 0" className="atlas-mouth" />
  </g>;
}
