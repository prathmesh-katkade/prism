"use client";

/**
 * Cortex V3: the same durable graph CortexV1 rendered as flat SVG, now as an
 * immersive 3D scene. This file owns presentation only -- every fact it
 * draws (which nodes exist, their kind/state, which plan step a node maps
 * to) comes from `atlas-cortex-shared`, unchanged from the SVG version. The
 * scene never fabricates activity: the core "breathes" ambiently at rest and
 * only glows/pulses faster when `run.plan.state === "running"`, exactly the
 * one real signal CortexV1 used for its own `data-active` flag.
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
import { connectedStepIdForNode, cortexPositions3D, cortexTone, type CortexTone, type Vec3 } from "./atlas-cortex-shared";

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

export function AtlasCortex3D({ graph, run, selectedStepId, onSelectStep }: { graph: CortexGraphState; run: AtlasRunResponse; selectedStepId: string | null; onSelectStep(stepId: string): void }) {
  const [focus, setFocus] = useState<string | null>(null);
  const [distance, setDistance] = useState(7);
  const nodes = useMemo(() => graph.nodes ?? [], [graph]);
  const edges = graph.edges ?? [];
  const kinds = useMemo(() => [...new Set(nodes.map((node) => node.kind))].sort(), [nodes]);
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set());
  const positions = useMemo(() => cortexPositions3D(nodes), [nodes]);
  const reducedMotion = useReducedMotion();
  const webglSupported = useWebglSupported();
  const runNode = nodes.find((node) => node.kind === "run") ?? null;
  const active = run.plan.state === "running";

  function isVisible(node: CortexNode) {
    return !hiddenKinds.has(node.kind) && (!focus || node.node_id === focus || edges.some((edge) => (edge.source_node_id === focus && edge.target_node_id === node.node_id) || (edge.target_node_id === focus && edge.source_node_id === node.node_id)));
  }
  function selectNode(node: CortexNode) {
    setFocus(node.node_id);
    const stepId = connectedStepIdForNode(node, run);
    if (stepId) onSelectStep(stepId);
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
          <p>{nodes.length} real nodes · {edges.length} real relations · {active ? "the core and its active step are glowing from this run's real, persisted state." : "ambient layout only; no event flow is implied."}</p>
        </div>
        <div className="cortex-controls">
          <button onClick={() => setDistance((value) => Math.max(4, value - 0.8))} aria-label="Zoom in Cortex">+</button>
          <button onClick={() => setDistance((value) => Math.min(11, value + 0.8))} aria-label="Zoom out Cortex">−</button>
          <button onClick={() => setFocus(null)} disabled={!focus}>Reset focus</button>
        </div>
      </header>
      <div className="cortex-filters" role="group" aria-label="Filter Cortex by node kind">
        {kinds.map((kind) => <button key={kind} type="button" className={`migration-chip ${hiddenKinds.has(kind) ? "" : "ready"}`} aria-pressed={!hiddenKinds.has(kind)} onClick={() => toggleKind(kind)}>{kind.replaceAll("_", " ")}</button>)}
      </div>
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
            <CortexCore active={active} reducedMotion={reducedMotion} onClick={() => runNode && selectNode(runNode)} selected={runNode ? connectedStepIdForNode(runNode, run) === selectedStepId : false} />
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
              const connectedStepId = connectedStepIdForNode(node, run);
              return (
                <CortexNodeMesh
                  key={node.node_id}
                  node={node}
                  position={position}
                  muted={!isVisible(node)}
                  selected={connectedStepId === selectedStepId}
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
      <ul className="cortex-node-list" aria-label="Cortex nodes">
        {nodes.map((node) => (
          <li key={node.node_id}>
            <button type="button" data-tone={cortexTone(node.state)} data-muted={!isVisible(node)} aria-pressed={node.node_id === focus} onClick={() => selectNode(node)} aria-label={`Focus ${node.label}`}>
              {node.label} <small>{node.kind.replaceAll("_", " ")} · {node.state}</small>
            </button>
          </li>
        ))}
      </ul>
      {focusedNode ? (
        <dl className="cortex-detail" aria-label="Selected Cortex node">
          <dt>Kind</dt><dd>{focusedNode.kind.replaceAll("_", " ")}</dd>
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

function CortexNodeMesh({ node, position, muted, selected, reducedMotion, onClick }: { node: CortexNode; position: Vec3; muted: boolean; selected: boolean; reducedMotion: boolean; onClick(): void }) {
  const mesh = useRef<Mesh>(null);
  const tone = cortexTone(node.state);
  const color = TONE_COLOR[tone];
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
