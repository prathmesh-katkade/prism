"use client";

import dynamic from "next/dynamic";
import React from "react";

const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => <textarea className="query-editor-fallback" aria-label="SQL query editor loading" readOnly value="Loading Query Studio editor…" />
});

export interface QueryEditorProps {
  value: string;
  dialect: string;
  schemaItems: readonly string[];
  onChange(value: string): void;
  onRun(): void;
}

/** PRISM-owned editor boundary; Monaco can be replaced without leaking its API into SQL Lab state. */
export function QueryEditor({ value, dialect, schemaItems, onChange, onRun }: QueryEditorProps) {
  return <div className="query-editor" onKeyDown={(event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault(); onRun();
    }
  }}>
    <MonacoEditor
      height="310px"
      language="sql"
      value={value}
      onChange={(next) => onChange(next ?? "")}
      onMount={(editor, monaco) => {
        monaco.languages.registerCompletionItemProvider("sql", {
          provideCompletionItems: (_model, position) => ({ suggestions: schemaItems.map((name) => ({
            label: name, kind: monaco.languages.CompletionItemKind.Field, insertText: name, detail: `PRISM schema · ${dialect}`,
            range: new monaco.Range(position.lineNumber, position.column, position.lineNumber, position.column)
          })) })
        });
        editor.addAction({ id: "prism.run-query", label: "PRISM: Run query", keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter], run: () => onRun() });
        editor.addAction({ id: "prism.format-query", label: "PRISM: Format query", keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyF], run: () => editor.getAction("editor.action.formatDocument")?.run() });
        editor.addAction({
          id: "prism.uppercase-selection",
          label: "PRISM: Uppercase selection",
          keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyU],
          run: () => {
            const selections = editor.getSelections() ?? [];
            editor.executeEdits("prism.uppercase-selection", selections.map((selection) => ({ range: selection, text: editor.getModel()?.getValueInRange(selection).toUpperCase() ?? "" })));
          }
        });
      }}
      theme="vs-dark"
      options={{
        accessibilitySupport: "on", automaticLayout: true, fontSize: 13, minimap: { enabled: false },
        multiCursorModifier: "ctrlCmd", padding: { top: 14 }, quickSuggestions: true, suggestOnTriggerCharacters: true,
        tabSize: 2, wordWrap: "on"
      }}
      aria-label={`PRISM Query Studio editor · ${dialect}`}
    />
  </div>;
}
