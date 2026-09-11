"use client";

import { useEffect, useState } from "react";
import type { PersistedLayout } from "./shell-model";

const storageKey = "prism.shell.layout.v1";

const defaults: PersistedLayout = {
  theme: "dark",
  density: "comfortable",
  railCollapsed: false,
  railWidth: 238,
  inspectorOpen: true,
  inspectorWidth: 292,
  atlasExpanded: false,
  splitView: false
};

function readStoredLayout(): PersistedLayout {
  if (typeof window === "undefined") return defaults;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(storageKey) ?? "{}") as Partial<PersistedLayout>;
    return { ...defaults, ...parsed };
  } catch {
    return defaults;
  }
}

export function useLayoutState() {
  const [layout, setLayout] = useState<PersistedLayout>(defaults);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setLayout(readStoredLayout());
    setReady(true);
  }, []);

  useEffect(() => {
    if (ready) window.localStorage.setItem(storageKey, JSON.stringify(layout));
  }, [layout, ready]);

  function updateLayout(patch: Partial<PersistedLayout>) {
    setLayout((previous) => ({ ...previous, ...patch }));
  }

  return { layout, updateLayout, ready };
}
