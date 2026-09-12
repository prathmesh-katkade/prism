"use client";

/**
 * Cortex V3: the same durable graph CortexV1 rendered as flat SVG, now as an
 * immersive 3D scene. This file owns presentation only -- every fact it
 * draws (which nodes exist, their kind/state, which plan step a node maps
 * to, how far the real pipeline has progressed) comes from
 * `atlas-cortex-shared` / `atlas-run-activity`, unchanged from the SVG
 * version. The scene never fabricates activity: the core "breathes"
 * ambiently at rest and only glows/pulses faster when
 * `run.plan.state === "running"`, exactly the one real signal CortexV1 used
 * for its own `data-active` flag.
 *
 * With no run at all yet, the scene still renders -- just the breathing
 * core, no invented nodes -- so ATLAS's idle screen has a real presence
 * rather than an empty box.
 *
 * WebGL is optional, not assumed: a browser without it (and every unit test
 * running under jsdom, which has no WebGL context at all) gets a static CSS
 * orb instead of a crash. A real, keyboard-operable button list mirrors
 * every node the canvas draws, so pointer users get the 3D scene and
 * keyboard/screen-reader users get the identical set of facts and actions
 * without depending on canvas hit-testing.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Line, OrbitControls } from "@react-three/drei";
import type { Group, Mesh } from "three";
import type { AtlasRunResponse, CortexGraphState, CortexNode } from "@prism/api-contracts";
import { PIPELINE_STAGES, guardrailDecisionFor, pipelineStageIndex } from "./atlas-run-activity";
import { PIPELINE_RING_RADIUS, connectedStepIdForNode, cortexPositions3D, cortexTone, isMemoryNode, type CortexSelection, type CortexTone, type Vec3 } from "./atlas-cortex-shared";

const TONE_COLOR: Record<CortexTone, string> = { idle: "#5b6b74", active: "#22d3ee", good: "#34d399", danger: "#f87171" };

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const onChange = () => setReduced(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/** Real WebGL support, probed once on mount rather than assumed -- jsdom
 * (every unit test) and a locked-down browser both report `false` here,
 * and both get the same honest static fallback rather than a thrown error. */
function useWebglSupported(): boolean | null {
  const [supported, setSupported] = useState<boolean | null>(null);
  useEffect(() => {
    try {
      const probe = document.createElement("canvas");
      const context = probe.getContext("webgl2") ?? probe.getContext("webgl");
      setSupported(Boolean(context));
    } catch {
      setSupported(false);
    }
  }, []);
  return supported;
}

export function AtlasCortex3D({
  graph,
  run,
  selectedStepId,
  onSelectStep,
  onSelectNode,
}: {
  graph: CortexGraphState | null;
  run: AtlasRunResponse | null;
  selectedStepId: string | null;
  onSelectStep(stepId: string): void;
  onSelectNode?(selection: CortexSelection): void;
}) {
  const [focus, setFocus] = useState<string | null>(null);
  const [distance, setDistance] = useState(7);
  // A node_id (and, for shared specialist/tool ids, the step it resolved to)
  // is only meaningful for the run that produced it. Starting a new
  // investigation replaces `run`/`graph` in place rather than remounting this
  // component, so a stale focus would otherwise either mute every node in the
  // new graph (isVisible) or point the parent's selection at the wrong step.
  useEffect(() => { setFocus(null); }, [run?.run_id]);
  const nodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const edges = graph?.edges ?? [];
  const kinds = useMemo(() => [...new Set(nodes.map((node) => node.kind))].sort(), [nodes]);
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set());
  const positions = useMemo(() => cortexPositions3D(nodes), [nodes]);
  const reducedMotion = useReducedMotion();
  const webglSupported = useWebglSupported();
  const runNode = nodes.find((node) => node.kind === "run") ?? null;
  const active = run?.plan.state === "running";

  function isVisible(node: CortexNode) {
    return !hiddenKinds.has(node.kind) && (!focus || node.node_id === focus || edges.some((edge) => (edge.source_node_id === focus && edge.target_node_id === node.node_id) || (edge.target_node_id === focus && edge.source_node_id === node.node_id)));
  }
  function selectNode(node: CortexNode) {
    setFocus(node.node_id);
    onSelectNode?.({ kind: "node", node });
    if (!run) return;
    const stepId = connectedStepIdForNode(node, run);
    if (stepId) onSelectStep(stepId);
  }
  function selectCore() {
    setFocus(runNode?.node_id ?? null);
    onSelectNode?.({ kind: "core" });
    if (run && runNode) {
      const stepId = connectedStepIdForNode(runNode, run);
      if (stepId) onSelectStep(stepId);
    }
  }
  function toggleKind(kind: string) {
    setHiddenKinds((previous) => {
      const next = new Set(previous);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }
  const focusedNode = focus ? nodes.find((node) => node.node_id === focus) ?? null : null;

  return (
    <section className="cortex-v1 cortex-3d" aria-label="Cortex real-state graph">
      <header>
        <div>
          <span className="eyebrow">CORTEX · DURABLE STATE ONLY</span>
          <h2>Run topology</h2>
          <p>{run ? <>{nodes.length} real nodes · {edges.length} real relations · {active ? "the core and its active step are glowing from this run's real, persisted state." : "ambient layout only; no event flow is implied."}</> : "No investigation has run yet. The core is idle -- ambient only, never implying reasoning."}</p>
        </div>
        <div className="cortex-controls">
          <button onClick={() => setDistance((value) => Math.max(4, value - 0.8))} aria-label="Zoom in Cortex">+</button>
          <button onClick={() => setDistance((value) => Math.min(11, value + 0.8))} aria-label="Zoom out Cortex">−</button>
          <button onClick={() => setFocus(null)} disabled={!focus}>Reset focus</button>
        </div>
      </header>
      {kinds.length ? (
        <div className="cortex-filters" role="group" aria-label="Filter Cortex by node kind">
          {kinds.map((kind) => <button key={kind} type="button" className={`migration-chip ${hiddenKinds.has(kind) ? "" : "ready"}`} aria-pressed={!hiddenKinds.has(kind)} onClick={() => toggleKind(kind)}>{kind.replaceAll("_", " ")}</button>)}
        </div>
      ) : null}
      <div className="cortex-stage" data-active={active}>
        {webglSupported ? (
          <Canvas
            dpr={[1, 1.5]}
            camera={{ position: [0, 2.2, distance], fov: 48 }}
            gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
            frameloop={reducedMotion ? "demand" : "always"}
            aria-hidden="true"
          >
            <ambientLight intensity={0.55} />
            <pointLight position={[4, 5, 4]} intensity={30} color="#7dd3fc" />
            <pointLight position={[-4, -3, -4]} intensity={12} color="#22d3ee" />
            <CortexCore active={active} reducedMotion={reducedMotion} onClick={selectCore} selected={Boolean(runNode) && focus === runNode?.node_id} />
            {run ? <CortexPipelineRing run={run} reducedMotion={reducedMotion} /> : null}
            {edges.map((edge) => {
              const a = positions[edge.source_node_id];
              const b = positions[edge.target_node_id];
              if (!a || !b) return null;
              const muted = Boolean(focus) && edge.source_node_id !== focus && edge.target_node_id !== focus;
              return <CortexEdgeLine key={edge.edge_id} a={a} b={b} muted={muted} active={active} reducedMotion={reducedMotion} />;
            })}
            {nodes.filter((node) => node.kind !== "run").map((node) => {
              const position = positions[node.node_id];
              if (!position) return null;
              const connectedStepId = run ? connectedStepIdForNode(node, run) : null;
              return (
                <CortexNodeMesh
                  key={node.node_id}
                  node={node}
                  position={position}
                  muted={!isVisible(node)}
                  selected={connectedStepId !== null && connectedStepId === selectedStepId}
                  reducedMotion={reducedMotion}
                  onClick={() => selectNode(node)}
                />
              );
            })}
            <OrbitControls enablePan={false} minDistance={4} maxDistance={11} autoRotate={!reducedMotion && !focus} autoRotateSpeed={0.5} target={[0, 0, 0]} />
          </Canvas>
        ) : (
          <div className="cortex-stage-fallback" aria-hidden="true">
            <span className={`cortex-orb-static${active ? " is-active" : ""}`} />
          </div>
        )}
      </div>
      {/* Accessible mirror of every node the canvas draws: real, focusable
          buttons carrying the exact facts and click behavior the 3D meshes
          have, so keyboard and screen-reader use never depends on canvas
          hit-testing -- a compact, always-visible chip row rather than an
          off-screen duplicate, so it stays genuinely clickable too. */}
      {nodes.length ? (
        <ul className="cortex-node-list" aria-label="Cortex nodes">
          {nodes.map((node) => (
            <li key={node.node_id}>
              <button type="button" data-tone={cortexTone(node.state)} data-memory={isMemoryNode(node)} data-muted={!isVisible(node)} aria-pressed={node.node_id === focus} onClick={() => selectNode(node)} aria-label={`Focus ${node.label}`}>
                {node.label} <small>{isMemoryNode(node) ? "memory" : node.kind.replaceAll("_", " ")} · {node.state}</small>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {focusedNode ? (
        <dl className="cortex-detail" aria-label="Selected Cortex node">
          <dt>Kind</dt><dd>{isMemoryNode(focusedNode) ? "memory" : focusedNode.kind.replaceAll("_", " ")}</dd>
          <dt>Label</dt><dd>{focusedNode.label}</dd>
          <dt>State</dt><dd>{focusedNode.state}</dd>
          <dt>Source ID</dt><dd className="acc-mono">{focusedNode.source_id}</dd>
        </dl>
      ) : null}
      <ul className="cortex-legend">
        <li>Running / current</li>
        <li>Recorded evidence</li>
        <li>Blocked or cancelled</li>
      </ul>
    </section>
  );
}

/** The central core: an idle "breath" always plays (ambient only, never
 * implying thinking); a real running plan raises its pulse rate and swaps
 * its tone to the active color -- the one and only activity signal. */
function CortexCore({ active, reducedMotion, selected, onClick }: { active: boolean; reducedMotion: boolean; selected: boolean; onClick(): void }) {
  const mesh = useRef<Mesh>(null);
  const clock = useRef(0);
  useFrame((_, delta) => {
    if (reducedMotion) return;
    clock.current += delta;
    const rate = active ? 2.6 : 0.6;
    const amplitude = active ? 0.1 : 0.05;
    const scale = 1 + Math.sin(clock.current * rate) * amplitude;
    if (mesh.current) mesh.current.scale.setScalar(scale);
  });
  const color = active ? TONE_COLOR.active : "#8fb4c4";
  return (
    <mesh ref={mesh} onClick={(event) => { event.stopPropagation(); onClick(); }}>
      <icosahedronGeometry args={[0.85, 1]} />
      <meshStandardMaterial color={color} emissive={color} emissiveIntensity={active ? 0.9 : 0.35} roughness={0.35} metalness={0.2} wireframe={!active} />
      {selected ? <mesh scale={1.35}><icosahedronGeometry args={[0.85, 0]} /><meshBasicMaterial color={color} wireframe transparent opacity={0.4} /></mesh> : null}
    </mesh>
  );
}

/** Decorative-only reinforcement of the real, accessible `<PipelineStepper>`
 * strip: seven arc segments, one per REQUEST->RESULT stage, colored and lit
 * by the exact same `pipelineStageIndex`/`guardrailDecisionFor` real state
 * that strip uses -- never a second, independent notion of progress. Purely
 * `aria-hidden` (inside the canvas), so it adds nothing a keyboard or
 * screen-reader user could miss. */
function CortexPipelineRing({ run, reducedMotion }: { run: AtlasRunResponse; reducedMotion: boolean }) {
  const reached = pipelineStageIndex(run);
  const decision = guardrailDecisionFor(run);
  const blockedAtGuardrail = decision !== null && decision.state !== "checked";
  const total = PIPELINE_STAGES.length;
  return (
    <group rotation={[-Math.PI / 2, 0, 0]}>
      {PIPELINE_STAGES.map((stage, index) => {
        const isReached = index <= reached;
        const isCurrent = index === reached && index < total - 1;
        const held = blockedAtGuardrail && index > 2;
        const tone: CortexTone = held ? "danger" : isCurrent ? "active" : isReached ? "good" : "idle";
        const span = (Math.PI * 2) / total;
        return <PipelineRingSegment key={stage.id} thetaStart={index * span + 0.05} thetaLength={span * 0.82} tone={tone} pulsing={isCurrent} reducedMotion={reducedMotion} />;
      })}
    </group>
  );
}

function PipelineRingSegment({ thetaStart, thetaLength, tone, pulsing, reducedMotion }: { thetaStart: number; thetaLength: number; tone: CortexTone; pulsing: boolean; reducedMotion: boolean }) {
  const mesh = useRef<Mesh>(null);
  const clock = useRef(0);
  const color = TONE_COLOR[tone];
  const baseOpacity = tone === "idle" ? 0.16 : tone === "active" ? 0.85 : 0.5;
  useFrame((_, delta) => {
    if (reducedMotion || !pulsing || !mesh.current) return;
    clock.current += delta;
    const material = mesh.current.material as unknown as { opacity: number };
    material.opacity = baseOpacity + Math.sin(clock.current * 3) * 0.15;
  });
  return (
    <mesh ref={mesh}>
      <ringGeometry args={[PIPELINE_RING_RADIUS - 0.04, PIPELINE_RING_RADIUS + 0.04, 32, 1, thetaStart, thetaLength]} />
      <meshBasicMaterial color={color} transparent opacity={baseOpacity} side={2} />
    </mesh>
  );
}

function CortexNodeMesh({ node, position, muted, selected, reducedMotion, onClick }: { node: CortexNode; position: Vec3; muted: boolean; selected: boolean; reducedMotion: boolean; onClick(): void }) {
  const mesh = useRef<Mesh>(null);
  const tone = cortexTone(node.state);
  const color = isMemoryNode(node) ? "#a78bfa" : TONE_COLOR[tone];
  const clock = useRef(Math.random() * Math.PI * 2); // phase offset only, never affects position -- purely visual desync so nodes don't pulse in lockstep
  useFrame((_, delta) => {
    if (reducedMotion || tone !== "active") return;
    clock.current += delta;
    const scale = 1 + Math.sin(clock.current * 3) * 0.12;
    if (mesh.current) mesh.current.scale.setScalar(scale);
  });
  return (
    <group position={position as unknown as [number, number, number]}>
      <mesh ref={mesh} onClick={(event) => { event.stopPropagation(); onClick(); }}>
        <sphereGeometry args={[node.kind === "evidence" ? 0.22 : 0.28, 20, 20]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={muted ? 0.05 : selected ? 0.85 : 0.4} transparent opacity={muted ? 0.18 : 1} roughness={0.4} />
      </mesh>
      {selected ? <mesh scale={1.6}><sphereGeometry args={[node.kind === "evidence" ? 0.22 : 0.28, 16, 16]} /><meshBasicMaterial color={color} wireframe transparent opacity={0.5} /></mesh> : null}
    </group>
  );
}

function CortexEdgeLine({ a, b, muted, active, reducedMotion }: { a: Vec3; b: Vec3; muted: boolean; active: boolean; reducedMotion: boolean }) {
  const group = useRef<Group>(null);
  const points = useMemo(() => [a, b] as [Vec3, Vec3], [a, b]);
  useFrame(({ clock }) => {
    if (reducedMotion || !active || muted || !group.current) return;
    const material = (group.current.children[0] as unknown as { material?: { dashOffset: number } })?.material;
    if (material) material.dashOffset = -clock.getElapsedTime() * 1.2;
  });
  return (
    <group ref={group}>
      <Line points={points as unknown as [number, number, number][]} color={active ? "#22d3ee" : "#465b64"} transparent opacity={muted ? 0.08 : active ? 0.65 : 0.35} lineWidth={1} dashed={active} dashSize={0.18} gapSize={0.12} />
    </group>
  );
}
