"use client";

/** The approved layered data-tile character, in three stateful expressions.
 * The assets are transparent PNGs kept with the web build so the packaged
 * desktop and browser use the same local files. No decorative animation. */
export type AtlasPose = "idle" | "working" | "presenting" | "waiting";

const POSE_LABEL: Record<AtlasPose, string> = {
  idle: "watching",
  working: "working",
  presenting: "presenting evidence",
  waiting: "waiting for your input",
};

export function AtlasCharacter({ pose = "idle", size = "small", className }: { pose?: AtlasPose; size?: "small" | "large"; className?: string }) {
  const file = pose === "working" ? "working" : pose === "waiting" ? "waiting" : "presenting";
  const width = size === "large" ? 72 : 28;
  return <img
    className={`atlas-character atlas-character-${size}${className ? ` ${className}` : ""}`}
    src={`/atlas/data-tile-${file}.png`}
    width={width}
    height={width}
    alt={`Atlas, ${POSE_LABEL[pose]}`}
    decoding="async"
  />;
}
