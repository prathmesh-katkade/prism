import React, { type SVGProps } from "react";

export type IconName = "command" | "grid" | "database" | "spark" | "panel" | "split" | "sun" | "moon" | "arrow" | "close" | "collapse" | "check" | "clock" | "layers" | "help" | "alert" | "link";

const paths: Record<IconName, string> = {
  command: "M9 4 5 8l4 4M15 4l4 4-4 4M5 16h14",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  database: "M12 4c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3Zm8 3v10c0 1.7-3.6 3-8 3s-8-1.3-8-3V7m16 5c0 1.7-3.6 3-8 3s-8-1.3-8-3",
  spark: "m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Zm6 12 .8 2.2L21 18l-2.2.8L18 21l-.8-2.2L15 18l2.2-.8L18 15Z",
  panel: "M4 5h16v14H4zM10 5v14",
  split: "M4 5h16v14H4zM12 5v14",
  sun: "M12 3v2m0 14v2m9-9h-2M5 12H3m15.4-6.4L17 7m-10 10-1.4 1.4m12.8 0L17 17M7 7 5.6 5.6M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
  moon: "M20 15.2A8 8 0 1 1 8.8 4 6.2 6.2 0 0 0 20 15.2Z",
  arrow: "m9 18 6-6-6-6",
  close: "m6 6 12 12M18 6 6 18",
  collapse: "M8 5 3 10l5 5M16 5l5 5-5 5M4 10h16",
  check: "m4 12 5 5L20 6",
  clock: "M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm0-12v4l3 2",
  layers: "m12 3 8 4.5-8 4.5-8-4.5L12 3Zm-8 8.5 8 4.5 8-4.5M4 16l8 4.5 8-4.5",
  help: "M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.9.4-1.5 1-1.5 2.2v.5M12 17.5v.1M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z",
  alert: "M12 3 2 20h20L12 3Zm0 6v5m0 3v.1",
  link: "M9 15l6-6M8.5 12.5 6 15a3 3 0 1 0 4.2 4.2l2.5-2.5M15.5 11.5 18 9a3 3 0 1 0-4.2-4.2l-2.5 2.5"
};

export function Icon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" {...props}><path d={paths[name]} /></svg>;
}
