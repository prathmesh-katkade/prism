"use client";

import React, { useEffect, useRef, useState } from "react";
import { Icon } from "./icons";

export interface CommandItem {
  id: string;
  label: string;
  description: string;
  shortcut?: string;
  disabled?: boolean;
  run(): void;
}

export function CommandPalette({ open, commands, onClose }: { open: boolean; commands: readonly CommandItem[]; onClose(): void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const available = commands.filter((command) => `${command.label} ${command.description}`.toLowerCase().includes(query.toLowerCase()));

  useEffect(() => {
    if (open) {
      setQuery("");
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  if (!open) return null;
  return (
    <div className="command-layer" role="presentation" onMouseDown={onClose}>
      <section className="command-palette" role="dialog" aria-modal="true" aria-label="PRISM command surface" onMouseDown={(event) => event.stopPropagation()}>
        <div className="command-input-row"><Icon name="command" /><input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search commands, workspaces, objects…" aria-label="Search commands" /><kbd>Esc</kbd></div>
        <div className="command-results" role="listbox" aria-label="Available commands">
          {available.map((command) => <button key={command.id} role="option" disabled={command.disabled} onClick={() => { command.run(); onClose(); }}><span><strong>{command.label}</strong><small>{command.description}</small></span>{command.shortcut ? <kbd>{command.shortcut}</kbd> : <Icon name="arrow" />}</button>)}
          {available.length === 0 ? <p className="command-empty">No matching commands.</p> : null}
        </div>
      </section>
    </div>
  );
}
