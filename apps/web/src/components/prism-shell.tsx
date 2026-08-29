"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import type { MigrationState } from "@prism/api-contracts";
import { CommandPalette, type CommandItem } from "./command-palette";
import { Icon, type IconName } from "./icons";
import { OverviewWorkspace } from "./overview-workspace";
import { QueryStudio } from "./query-studio";
import { AiAnalyst } from "./ai-analyst";
import { CleanWorkspace } from "./clean-workspace";
import { VisualizeWorkspace } from "./visualize-workspace";
import { StatsWorkspace } from "./stats-workspace";
import { ForecastingWorkspace } from "./forecasting-workspace";
import { migrationPresentation, phaseTwoMigrations, type InspectorObjectState, type ShellStatus, type WorkspaceTab } from "../state/shell-model";
import { useLayoutState } from "../state/use-layout-state";

const baseTab: WorkspaceTab = { id: "project", label: "Project desk", kind: "home", closeable: false };

const navigation: ReadonlyArray<{ workflow: string; label: string; icon: IconName }> = [
  { workflow: "overview", label: "Overview", icon: "grid" },
  { workflow: "sql-lab", label: "SQL Lab", icon: "database" },
  { workflow: "ai-analyst", label: "AI Analyst", icon: "spark" },
  { workflow: "clean", label: "Clean", icon: "grid" },
  { workflow: "visualize", label: "Visualize", icon: "grid" },
  { workflow: "stats", label: "Stats", icon: "grid" },
  { workflow: "forecasting", label: "Forecasting", icon: "grid" },
  { workflow: "ml", label: "ML", icon: "spark" }
];

function findMigration(workflow: string): MigrationState {
  return phaseTwoMigrations.find((migration) => migration.workflow === workflow) ?? phaseTwoMigrations[0]!;
}

const nativeKinds: Record<string, WorkspaceTab["kind"]> = { overview: "overview", "sql-lab": "sql-lab", "ai-analyst": "ai-analyst", clean: "clean", visualize: "visualize", stats: "stats", forecasting: "forecasting" };

function workflowTab(workflow: string): WorkspaceTab {
  return { id: `workspace:${workflow}`, label: navigation.find((item) => item.workflow === workflow)?.label ?? workflow, kind: nativeKinds[workflow] ?? "bridge", workflow, closeable: true };
}

export function PrismShell() {
  const { layout, updateLayout, ready } = useLayoutState();
  const [tabs, setTabs] = useState<readonly WorkspaceTab[]>([baseTab]);
  const [activeTabId, setActiveTabId] = useState(baseTab.id);
  const [status, setStatus] = useState<ShellStatus>("project-loaded");
  const [commandOpen, setCommandOpen] = useState(false);
  const [selectedContext, setSelectedContext] = useState<InspectorObjectState | null>(null);
  const [sqlDraft, setSqlDraft] = useState<string | undefined>();
  const [analystResultRunId, setAnalystResultRunId] = useState<string | undefined>();
  const [activeDatasetId, setActiveDatasetId] = useState<string | undefined>();
  const commandTrigger = useRef<HTMLButtonElement>(null);
  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? baseTab;
  const activeMigration = activeTab.workflow ? findMigration(activeTab.workflow) : null;
  const inspector = selectedContext ?? inspectorFor(activeTab, activeMigration);

  function resizePanel(panel: "rail" | "inspector", clientX: number) {
    const width = panel === "rail" ? Math.max(180, Math.min(360, clientX)) : Math.max(240, Math.min(420, window.innerWidth - clientX));
    updateLayout(panel === "rail" ? { railWidth: width } : { inspectorWidth: width });
  }

  function startResize(panel: "rail" | "inspector", event: React.PointerEvent<HTMLDivElement>) {
    event.currentTarget.setPointerCapture(event.pointerId);
    const onMove = (moveEvent: PointerEvent) => resizePanel(panel, moveEvent.clientX);
    const onUp = () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  }

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandOpen(true);
      }
      if (event.key === "Escape" && commandOpen) {
        setCommandOpen(false);
        commandTrigger.current?.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [commandOpen]);

  function openWorkflow(workflow: string) {
    const next = workflowTab(workflow);
    setTabs((previous) => previous.some((tab) => tab.id === next.id) ? previous : [...previous, next]);
    setActiveTabId(next.id);
    setSelectedContext(null);
    setStatus(Object.keys(nativeKinds).includes(workflow) ? "project-loaded" : "migration-bridge");
  }

  function closeTab(id: string) {
    setTabs((previous) => previous.filter((tab) => tab.id !== id));
    if (activeTabId === id) setActiveTabId(baseTab.id);
  }

  function selectTab(id: string) {
    setActiveTabId(id);
    setSelectedContext(null);
  }

  /** Roving-tabindex arrow navigation for the tablist (WAI-ARIA tabs pattern, automatic activation).
   * Delete/Backspace closes the focused tab: the visual "×" button is a pointer-only shortcut
   * (aria-hidden, not in the tab order) so the tablist's accessible children stay exclusively
   * role="tab" elements with no nested focusable control - keyboard users close via this
   * shortcut on the tab itself instead. */
  function onTabListKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const currentIndex = tabs.findIndex((tab) => tab.id === activeTabId);
    if (currentIndex === -1) return;
    if (event.key === "Delete" || event.key === "Backspace") {
      const current = tabs[currentIndex]!;
      if (!current.closeable) return;
      event.preventDefault();
      closeTab(current.id);
      return;
    }
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
    else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = tabs.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = tabs[nextIndex]!;
    selectTab(nextTab.id);
    document.getElementById(`tab-${nextTab.id}`)?.focus();
  }

  const commands = useMemo<readonly CommandItem[]>(() => [
    { id: "open-project", label: "Open project desk", description: "Return to the shell overview", shortcut: "G P", run: () => { setActiveTabId(baseTab.id); setStatus("project-loaded"); } },
    { id: "toggle-inspector", label: layout.inspectorOpen ? "Hide inspector" : "Show inspector", description: "Toggle the contextual object panel", shortcut: "⌘ I", run: () => updateLayout({ inspectorOpen: !layout.inspectorOpen }) },
    { id: "toggle-split", label: layout.splitView ? "Close split view" : "Open split view", description: "Prepare a second tab group", shortcut: "⌘ \\ ", run: () => updateLayout({ splitView: !layout.splitView }) },
    { id: "toggle-density", label: "Toggle workspace density", description: "Switch between comfortable and compact", run: () => updateLayout({ density: layout.density === "comfortable" ? "compact" : "comfortable" }) },
    ...navigation.map((item) => ({ id: `open-${item.workflow}`, label: `Open ${item.label}`, description: `${migrationPresentation(findMigration(item.workflow))} migration surface`, disabled: false, run: () => openWorkflow(item.workflow) }))
  ], [layout.density, layout.inspectorOpen, layout.splitView]);

  return (
    <main className={`prism-shell theme-${layout.theme} density-${layout.density}`} data-ready={ready} style={{ "--rail-size": `${layout.railCollapsed ? 62 : layout.railWidth}px`, "--inspector-size": `${layout.inspectorWidth}px` } as React.CSSProperties}>
      <a className="skip-link" href="#workspace">Skip to workspace</a>
      <header className="topbar">
        <div className="wordmark" aria-label="PRISM workspace"><span className="prism-mark" />PRISM <small>RESEARCH SYSTEM</small></div>
        <div className="project-crumb"><span className="status-dot" /> <strong>Untitled research</strong><span>Local workspace</span></div>
        <div className="top-actions">
          <button className="command-trigger" ref={commandTrigger} onClick={() => setCommandOpen(true)} aria-haspopup="dialog"><Icon name="command" /> <span>Command surface</span><kbd>⌘ K</kbd></button>
          <button className="icon-button" aria-label={`Switch to ${layout.theme === "dark" ? "light" : "dark"} theme`} onClick={() => updateLayout({ theme: layout.theme === "dark" ? "light" : "dark" })}><Icon name={layout.theme === "dark" ? "sun" : "moon"} /></button>
        </div>
      </header>
      <div className="shell-body">
        <aside className={`nav-rail ${layout.railCollapsed ? "is-collapsed" : ""}`} aria-label="PRISM workspace navigation">
          <button className="rail-collapse" onClick={() => updateLayout({ railCollapsed: !layout.railCollapsed })} aria-label={layout.railCollapsed ? "Expand navigation" : "Collapse navigation"}><Icon name="collapse" /></button>
          <nav aria-label="Migration-aware workspaces">
            <p className="rail-label">WORKSPACES</p>
            {navigation.map((item) => {
              const migration = findMigration(item.workflow);
              const presentation = migrationPresentation(migration);
              return <button key={item.workflow} className={activeTab.workflow === item.workflow ? "nav-item is-active" : "nav-item"} onClick={() => openWorkflow(item.workflow)} title={layout.railCollapsed ? item.label : undefined}><Icon name={item.icon} /><span>{item.label}</span><i className={`migration-chip ${presentation}`}>{presentation}</i></button>;
            })}
          </nav>
          <div className="rail-footer"><button className="object-button" onClick={() => { setActiveTabId(baseTab.id); setStatus("project-loaded"); }}><Icon name="database" /><span>Data objects</span></button><small>Phase 7B · Forecasting native (enabled)</small></div>
        </aside>
        {!layout.railCollapsed ? <ResizeHandle panel="rail" value={layout.railWidth} onPointerDown={startResize} onKeyboardResize={(delta) => updateLayout({ railWidth: Math.max(180, Math.min(360, layout.railWidth + delta)) })} /> : <div className="resize-spacer" />}
        <section id="workspace" className="workspace-area" aria-label="Central tabbed workspace">
          <div className="workspace-tabs">
            <div className="workspace-tablist" role="tablist" aria-label="Open workspace tabs" onKeyDown={onTabListKeyDown}>
              {tabs.map((tab) => <div key={tab.id} id={`tab-${tab.id}`} className={tab.id === activeTabId ? "tab is-active" : "tab"} role="tab" aria-selected={tab.id === activeTabId} aria-controls={`panel-${tab.id}`} aria-keyshortcuts={tab.closeable ? "Delete" : undefined} tabIndex={tab.id === activeTabId ? 0 : -1} onClick={() => selectTab(tab.id)}><span>{tab.label}</span>{tab.closeable ? <span className="tab-close" aria-hidden="true" onClick={(event) => { event.stopPropagation(); closeTab(tab.id); }}><Icon name="close" /></span> : null}</div>)}
            </div>
            <div className="workspace-tab-actions"><button className="tab-add" aria-label="Open command surface" onClick={() => setCommandOpen(true)}>+</button><button className={layout.splitView ? "tab-tool is-active" : "tab-tool"} aria-label="Toggle split view" aria-pressed={layout.splitView} onClick={() => updateLayout({ splitView: !layout.splitView })}><Icon name="split" /></button></div>
          </div>
          <section id={`panel-${activeTab.id}`} role="tabpanel" aria-labelledby={`tab-${activeTab.id}`} className={layout.splitView ? "workspace-content split-enabled" : "workspace-content"}>
            <WorkspaceSurface tab={activeTab} status={status} onStatusChange={setStatus} onOpenCommand={() => setCommandOpen(true)} onSelectContext={setSelectedContext} onOpenWorkflow={openWorkflow} sqlDraft={sqlDraft} analystResultRunId={analystResultRunId} activeDatasetId={activeDatasetId} onDatasetReady={setActiveDatasetId} onSqlDraft={(draft) => { setSqlDraft(draft); openWorkflow("sql-lab"); }} onUseAsEvidence={(runId) => { setAnalystResultRunId(runId); openWorkflow("ai-analyst"); }} />
            {layout.splitView ? <aside className="split-foundation" aria-label="Secondary tab group foundation"><p>SECONDARY TAB GROUP</p><strong>Drop a tab here</strong><span>Split-view layout is saved locally. Analytical content does not duplicate here until its migration phase.</span></aside> : null}
          </section>
          <button className={layout.atlasExpanded ? "atlas-presence is-expanded" : "atlas-presence"} onClick={() => updateLayout({ atlasExpanded: !layout.atlasExpanded })} aria-expanded={layout.atlasExpanded} aria-label="Expand Atlas workspace"><span className="atlas-signal"><i /><i /><i /></span><span><strong>Atlas</strong><small>{layout.atlasExpanded ? "Context workspace ready" : "Watching workspace context"}</small></span><Icon name="arrow" /></button>
          {layout.atlasExpanded ? <section className="atlas-drawer" aria-label="Atlas contextual workspace"><div><span className="eyebrow">ATLAS · AMBIENT OPERATING PRESENCE</span><h2>What should we investigate?</h2><p>AI Analyst is native in Phase 5. Atlas keeps context compact, grounds responses in evidence, and requires SQL Lab review before execution.</p></div><button onClick={() => openWorkflow("ai-analyst")}>Open AI Analyst <kbd>⌘ K</kbd></button></section> : null}
        </section>
        {layout.inspectorOpen ? <><ResizeHandle panel="inspector" value={layout.inspectorWidth} onPointerDown={startResize} onKeyboardResize={(delta) => updateLayout({ inspectorWidth: Math.max(240, Math.min(420, layout.inspectorWidth + delta)) })} /><Inspector state={inspector} onClose={() => updateLayout({ inspectorOpen: false })} /></> : <><div className="resize-spacer" /><button className="inspector-restore" onClick={() => updateLayout({ inspectorOpen: true })} aria-label="Show inspector"><Icon name="panel" /></button></>}
      </div>
      <CommandPalette open={commandOpen} commands={commands} onClose={() => { setCommandOpen(false); commandTrigger.current?.focus(); }} />
    </main>
  );
}

function ResizeHandle({ panel, value, onPointerDown, onKeyboardResize }: { panel: "rail" | "inspector"; value: number; onPointerDown(panel: "rail" | "inspector", event: React.PointerEvent<HTMLDivElement>): void; onKeyboardResize(delta: number): void }) {
  return <div className={`resize-handle ${panel}`} role="separator" aria-label={`Resize ${panel === "rail" ? "navigation" : "inspector"}`} aria-orientation="vertical" aria-valuemin={panel === "rail" ? 180 : 240} aria-valuemax={panel === "rail" ? 360 : 420} aria-valuenow={value} tabIndex={0} onPointerDown={(event) => onPointerDown(panel, event)} onKeyDown={(event) => { if (event.key === "ArrowLeft") onKeyboardResize(-12); if (event.key === "ArrowRight") onKeyboardResize(12); }} />;
}

function WorkspaceSurface({ tab, status, onStatusChange, onOpenCommand, onSelectContext, onOpenWorkflow, sqlDraft, analystResultRunId, activeDatasetId, onDatasetReady, onSqlDraft, onUseAsEvidence }: { tab: WorkspaceTab; status: ShellStatus; onStatusChange(status: ShellStatus): void; onOpenCommand(): void; onSelectContext(state: InspectorObjectState): void; onOpenWorkflow(workflow: string): void; sqlDraft: string | undefined; analystResultRunId: string | undefined; activeDatasetId: string | undefined; onDatasetReady(datasetId: string): void; onSqlDraft(draft: string): void; onUseAsEvidence(runId: string): void }) {
  if (tab.kind === "overview") return <OverviewWorkspace activeDatasetId={activeDatasetId} onSelectContext={onSelectContext} onOpenWorkflow={onOpenWorkflow} onDatasetReady={onDatasetReady} />;
  if (tab.kind === "sql-lab") return <QueryStudio onSelectContext={onSelectContext} {...(sqlDraft ? { initialSql: sqlDraft } : {})} onUseAsEvidence={onUseAsEvidence} />;
  if (tab.kind === "ai-analyst") return <AiAnalyst resultRunId={analystResultRunId} onSqlDraft={onSqlDraft} />;
  if (tab.kind === "clean") return <CleanWorkspace datasetId={activeDatasetId} onSelectContext={onSelectContext} onOpenWorkflow={onOpenWorkflow} />;
  if (tab.kind === "visualize") return <VisualizeWorkspace datasetId={activeDatasetId} onSelectContext={onSelectContext} onOpenWorkflow={onOpenWorkflow} />;
  if (tab.kind === "stats") return <StatsWorkspace datasetId={activeDatasetId} onSelectContext={onSelectContext} onOpenWorkflow={onOpenWorkflow} />;
  if (tab.kind === "forecasting") return <ForecastingWorkspace datasetId={activeDatasetId} onSelectContext={onSelectContext} onOpenWorkflow={onOpenWorkflow} />;
  if (tab.kind === "bridge" && tab.workflow) {
    const migration = findMigration(tab.workflow);
    return <article className="bridge-surface"><span className="eyebrow">MIGRATION BRIDGE · {migrationPresentation(migration).toUpperCase()}</span><h1>{tab.label} remains in the reference system.</h1><p>This shell exposes a single migration-aware entry point without reimplementing or shadowing the underlying Streamlit workflow.</p><dl><div><dt>Reference</dt><dd><code>{migration.legacy_reference}</code></dd></div><div><dt>Parity gate</dt><dd>Required before this can become native.</dd></div><div><dt>Current channel</dt><dd><span className="migration-chip legacy">legacy</span></dd></div></dl><div className="bridge-actions"><button onClick={onOpenCommand}>Inspect migration controls</button><button className="secondary" onClick={() => onStatusChange("degraded")}>Preview degraded state</button></div></article>;
  }
  return <article className="project-desk"><div className="desk-heading"><div><span className="eyebrow">PROJECT DESK · SHELL STATE: {status}</span><h1>A quiet place to make evidence legible.</h1><p>Overview and SQL Lab are native. Remaining analytical workflows stay in Streamlit until their individual parity gates clear.</p></div><button onClick={onOpenCommand}>Open command surface <kbd>⌘ K</kbd></button></div><div className="state-strip" aria-label="Shell state previews"><button className={status === "empty" ? "is-selected" : ""} onClick={() => onStatusChange("empty")}>Empty</button><button className={status === "project-loaded" ? "is-selected" : ""} onClick={() => onStatusChange("project-loaded")}>Loaded</button><button className={status === "loading" ? "is-selected" : ""} onClick={() => onStatusChange("loading")}>Loading</button><button className={status === "degraded" ? "is-selected" : ""} onClick={() => onStatusChange("degraded")}>Degraded</button><button className={status === "error" ? "is-selected" : ""} onClick={() => onStatusChange("error")}>Error</button></div><ShellState status={status} /></article>;
}

function ShellState({ status }: { status: ShellStatus }) {
  if (status === "empty") return <section className="shell-state empty"><span className="state-illustration" /><h2>Begin with an object, not a dashboard.</h2><p>When a project is loaded, datasets and their research context will appear here.</p><button>Load local project</button></section>;
  if (status === "loading") return <section className="shell-state loading" aria-live="polite"><span className="loading-bar" /><h2>Establishing workspace context</h2><p>Validating project metadata and migration availability.</p></section>;
  if (status === "degraded") return <section className="shell-state degraded" role="status"><span className="signal-warning" /><h2>Some context is unavailable.</h2><p>The shell remains usable. No analytical workflow has been redirected or duplicated.</p><button>Retry platform check</button></section>;
  if (status === "error") return <section className="shell-state error" role="alert"><h2>PRISM could not establish the workspace.</h2><p>Inspect the connection state, then retry. Your layout remains preserved locally.</p><button>Retry</button></section>;
  return <section className="project-grid"><article><span className="card-index">01</span><h2>Migration clarity</h2><p>Eight product areas are visible with a single legacy/native/bridged state grammar.</p></article><article><span className="card-index">02</span><h2>Research posture</h2><p>Tabs, contextual inspection, and commands form the persistent analytical frame.</p></article><article><span className="card-index">03</span><h2>Desktop ready</h2><p>Layout state is local and browser-native, ready for future Tauri ownership.</p></article></section>;
}

function Inspector({ state, onClose }: { state: InspectorObjectState; onClose(): void }) {
  return <aside className="inspector" aria-label="Contextual inspector"><div className="inspector-heading"><div><span className="eyebrow">CONTEXT</span><h2>{state.label}</h2></div><button className="icon-button" onClick={onClose} aria-label="Hide inspector"><Icon name="close" /></button></div><dl className="inspector-data"><div><dt>Object type</dt><dd>{state.type}</dd></div><div><dt>State</dt><dd><span className={`migration-chip ${state.state}`}>{state.state}</span></dd></div><div><dt>Inspector contract</dt><dd>object-state/v1</dd></div>{state.metadata?.map((item) => <div key={item}><dt>Evidence</dt><dd>{item}</dd></div>)}</dl><div className="inspector-actions"><span className="eyebrow">CONTEXT ACTIONS</span>{state.actions.map((action) => <button key={action.id} disabled={action.disabled}>{action.label}{action.shortcut ? <kbd>{action.shortcut}</kbd> : <Icon name="arrow" />}</button>)}</div><div className="drag-foundation" draggable onDragStart={(event) => event.dataTransfer.setData("text/plain", state.objectId ?? "project")}><span className="eyebrow">SEMANTIC DRAG FOUNDATION</span><p>Drag object context to a future tab group.</p></div></aside>;
}

function inspectorFor(tab: WorkspaceTab, migration: MigrationState | null): InspectorObjectState {
  if (migration) return { objectId: migration.workflow, label: tab.label, type: "workflow", state: migrationPresentation(migration), actions: [{ id: "open-reference", label: "Open legacy reference", disabled: migrationPresentation(migration) === "native" }, { id: "view-parity", label: "View parity status", disabled: true }] };
  return { objectId: "project", label: "Untitled research", type: "project", state: "ready", actions: [{ id: "project-settings", label: "Project settings", disabled: true }, { id: "layout-reset", label: "Reset layout", disabled: true }] };
}
