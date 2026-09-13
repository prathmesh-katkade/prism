"use client";

/**
 * Cortex V4: the grouped, immersive 3D scene. This file owns presentation
 * only -- every fact it draws (which satellites exist, their status, which
 * plan step a satellite maps to) comes from `atlas-cortex-shared`'s
 * `buildCortexGroups`/`cortexGroupPositions3D`, unchanged from the atomic
 * data. The scene never fabricates activity: the core "breathes" ambiently
 * at rest and only glows/pulses faster when `run.plan.state === "running"`,
 * exactly the one real signal the previous SVG/V3 scenes used.
 *
 * With no run at all yet, the scene still renders -- just the breathing
 * core, no invented satellites -- so ATLAS's idle screen has a real
 * presence rather than an empty box.
 *
 * WebGL is optional, not assumed: a browser without it (and every unit test
 * running under jsdom, which has no WebGL context at all), a browser that
 * loses its WebGL context mid-session, and an unexpected render error all
 * fall back to the same static CSS orb instead of a crash. A real,
 * keyboard-operable button list mirrors every group and every atomic node
 * the canvas draws, so pointer users get the 3D scene and keyboard/
 * screen-reader users get the identical set of facts and actions without
 * depending on canvas hit-testing.
 */
import { Component, useEffect, useMemo, useRef, useState } from "react";
import type { ElementRef, ReactNode } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Html, Line, OrbitControls } from "@react-three/drei";
import { AdditiveBlending, Color, ShaderMaterial } from "three";
import type { Group, Mesh } from "three";
import type { AtlasRunResponse, CortexGraphState, CortexNode } from "@prism/api-contracts";
import { buildCortexGroups, cortexGroupPositions3D, cortexTone, isMemoryNode, type CortexGroup, type CortexSelection, type CortexTone, type Vec3 } from "./atlas-cortex-shared";

const TONE_COLOR: Record<CortexTone, string> = { idle: "#4d6472", active: "#57ddf5", good: "#6fe3b4", danger: "#f5b95c" };
const CORE_COLOR = "#57ddf5";

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

/** Catches a genuine render/runtime failure inside the 3D tree (malformed
 * data, a driver quirk) and swaps to the same static fallback rather than
 * taking down the rest of the Atlas workspace with it. */
class CortexBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    // Intentionally silent beyond the fallback UI: no fabricated diagnostic
    // is shown to the user, and nothing here retries with invented data.
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export function AtlasCortex3D({
  graph,
  run,
  selectedStepId,
  onSelectStep,
  onSelectNode,
  stageOverlay,
}: {
  graph: CortexGraphState | null;
  run: AtlasRunResponse | null;
  selectedStepId: string | null;
  onSelectStep(stepId: string): void;
  onSelectNode?(selection: CortexSelection): void;
  // Rendered inside `.cortex-stage` (the canvas box itself, not the whole
  // section with its header and the real accessible content below the
  // canvas) so a caller's floating overlay -- the result panel -- stays
  // anchored to the canvas regardless of how tall the header or the
  // group-list/run-focus/disclosure content below it grows.
  stageOverlay?: ReactNode;
}) {
  const [focus, setFocus] = useState<string | null>(null);
  const [distance, setDistance] = useState(7.5);
  const [contextLost, setContextLost] = useState(false);
  const controlsRef = useRef<ElementRef<typeof OrbitControls>>(null);
  // A group/node id is only meaningful for the run that produced it.
  // Starting a new investigation replaces `run`/`graph` in place rather than
  // remounting this component, so a stale focus would otherwise either mute
  // every satellite in the new graph or point the parent's selection at the
  // wrong step.
  useEffect(() => { setFocus(null); }, [run?.run_id]);
  const nodes = useMemo(() => graph?.nodes ?? [], [graph]);
  const groups = useMemo(() => buildCortexGroups(graph, run), [graph, run]);
  const groupPositions = useMemo(() => cortexGroupPositions3D(groups), [groups]);
  const groupKinds = useMemo(() => [...new Set(groups.map((group) => group.kind))].sort(), [groups]);
  const [hiddenGroupKinds, setHiddenGroupKinds] = useState<Set<string>>(new Set());
  function toggleGroupKind(kind: string) {
    setHiddenGroupKinds((previous) => {
      const next = new Set(previous);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }
  function isGroupMuted(group: CortexGroup): boolean {
    return hiddenGroupKinds.has(group.kind) || (Boolean(focus) && focus !== group.groupId);
  }
  const reducedMotion = useReducedMotion();
  const webglSupported = useWebglSupported();
  const runNode = nodes.find((node) => node.kind === "run") ?? null;
  const active = run?.plan.state === "running";

  function mostRelevantStepId(group: CortexGroup): string | null {
    if (!run || group.kind !== "specialist") return null;
    const steps = (run.plan.steps ?? []).filter((step) => step.specialist === group.sourceId);
    const step = steps.find((item) => item.state === "running") ?? steps.find((item) => item.state === "blocked") ?? steps.find((item) => item.state === "failed") ?? steps[0];
    return step?.step_id ?? null;
  }
  function selectGroup(group: CortexGroup) {
    setFocus(group.groupId);
    onSelectNode?.({ kind: "group", group });
    const stepId = mostRelevantStepId(group);
    if (stepId) onSelectStep(stepId);
  }
  function selectNode(node: CortexNode) {
    setFocus(node.node_id);
    onSelectNode?.({ kind: "node", node });
  }
  function selectCore() {
    setFocus(runNode?.node_id ?? null);
    onSelectNode?.({ kind: "core" });
  }
  function resetView() {
    setFocus(null);
    setDistance(7.5);
    controlsRef.current?.reset();
  }
  const focusedGroup = focus ? groups.find((group) => group.groupId === focus) ?? null : null;
  // One unified selection-detail contract regardless of *what* was focused
  // (the core, an atomic node from the disclosure list, or a grouped
  // satellite) -- the same real facts, never a second notion of "selected".
  const focusedNode = focus ? nodes.find((node) => node.node_id === focus) ?? null : null;
  const selectionDetail = focusedNode
    ? { kind: isMemoryNode(focusedNode) ? "memory" : focusedNode.kind.replaceAll("_", " "), label: focusedNode.label, state: focusedNode.state, detail: focusedNode.source_id }
    : focusedGroup
      ? { kind: focusedGroup.kind, label: focusedGroup.label, state: focusedGroup.status, detail: `${focusedGroup.memberNodeIds.length} real node${focusedGroup.memberNodeIds.length === 1 ? "" : "s"} · ${focusedGroup.memberEdgeIds.length} real relation${focusedGroup.memberEdgeIds.length === 1 ? "" : "s"}` }
      : null;

  const fallback = (
    <div className="cortex-stage-fallback" aria-hidden="true">
      <span className={`cortex-orb-static${active ? " is-active" : ""}`} />
    </div>
  );

  return (
    <section className="cortex-v1 cortex-3d" aria-label="Cortex real-state graph">
      <header>
        <div>
          <span className="eyebrow">ATLAS · CORTEX</span>
          <h2>{run ? runHeading(run) : "Cortex"}</h2>
          <p>{run ? <>{nodes.length} real nodes · {(graph?.edges ?? []).length} real relations · {active ? "the core and its active satellite are glowing from this run's real, persisted state." : "grouped view of durable state -- ambient only, no event flow is implied."}</> : "No investigation has run yet. The core is idle -- ambient only, never implying reasoning."}</p>
        </div>
        <div className="cortex-controls">
          <button type="button" onClick={() => setDistance((value) => Math.max(4.5, value - 0.9))} aria-label="Zoom in Cortex">+</button>
          <button type="button" onClick={() => setDistance((value) => Math.min(12, value + 0.9))} aria-label="Zoom out Cortex">−</button>
          <button type="button" onClick={resetView} disabled={!focus && distance === 7.5}>Reset focus</button>
        </div>
      </header>
      {groupKinds.length ? (
        <div className="cortex-filters" role="group" aria-label="Filter Cortex by satellite kind">
          {groupKinds.map((kind) => <button key={kind} type="button" className={`migration-chip ${hiddenGroupKinds.has(kind) ? "" : "ready"}`} aria-pressed={!hiddenGroupKinds.has(kind)} onClick={() => toggleGroupKind(kind)}>{kind}</button>)}
        </div>
      ) : null}
      <div className="cortex-stage" data-active={active}>
        {stageOverlay}
        {webglSupported && !contextLost ? (
          <CortexBoundary fallback={fallback}>
            <Canvas
              dpr={[1, 1.5]}
              camera={{ position: [0, 2.1, distance], fov: 46 }}
              gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
              frameloop={reducedMotion ? "demand" : "always"}
              aria-hidden="true"
              onCreated={(state) => {
                const canvas = state.gl.domElement;
                const onLost = (event: Event) => { event.preventDefault(); setContextLost(true); };
                const onRestored = () => setContextLost(false);
                canvas.addEventListener("webglcontextlost", onLost);
                canvas.addEventListener("webglcontextrestored", onRestored);
              }}
            >
              <ambientLight intensity={0.5} />
              <pointLight position={[4, 5, 4]} intensity={26} color="#8fe9fb" />
              <pointLight position={[-4, -3, -4]} intensity={10} color="#57ddf5" />
              <CortexCore active={active} reducedMotion={reducedMotion} onClick={selectCore} selected={Boolean(runNode) && focus === runNode?.node_id} />
              <CortexRing radius={2.15} tiltX={0.55} tiltZ={0.12} opacity={0.4} reducedMotion={reducedMotion} speed={0.05} />
              <CortexRing radius={1.7} tiltX={-0.4} tiltZ={-0.28} opacity={0.26} reducedMotion={reducedMotion} speed={-0.035} />
              <CortexParticles reducedMotion={reducedMotion} active={active} />
              {groups.map((group) => {
                const position = groupPositions[group.groupId];
                if (!position) return null;
                return (
                  <CortexGroupConnection
                    key={`line:${group.groupId}`}
                    a={[0, 0, 0]}
                    b={position}
                    tone={group.tone}
                    muted={isGroupMuted(group)}
                    active={active}
                    reducedMotion={reducedMotion}
                    weight={group.memberEdgeIds.length}
                  />
                );
              })}
              {groups.map((group) => {
                const position = groupPositions[group.groupId];
                if (!position) return null;
                const connectedStepId = mostRelevantStepId(group);
                return (
                  <CortexGroupSatellite
                    key={group.groupId}
                    group={group}
                    position={position}
                    muted={isGroupMuted(group)}
                    selected={focus === group.groupId || (connectedStepId !== null && connectedStepId === selectedStepId)}
                    reducedMotion={reducedMotion}
                    onClick={() => selectGroup(group)}
                  />
                );
              })}
              <OrbitControls ref={controlsRef} enablePan={false} minDistance={4.5} maxDistance={12} target={[0, 0, 0]} autoRotate={!reducedMotion && !focus} autoRotateSpeed={0.4} />
            </Canvas>
          </CortexBoundary>
        ) : fallback}
      </div>
      {/* Accessible mirror of every satellite the canvas draws: real,
          focusable buttons carrying the exact facts and click behavior the
          3D meshes have, so keyboard and screen-reader use never depends on
          canvas hit-testing. This is the primary equivalent surface (styled
          to match the grouped satellites); the full atomic graph stays one
          disclosure away for provenance. */}
      {groups.length ? (
        <ul className="cortex-group-list" aria-label="Cortex satellites">
          {groups.map((group) => (
            <li key={group.groupId}>
              <button type="button" data-tone={group.tone} data-muted={isGroupMuted(group)} aria-pressed={group.groupId === focus} onClick={() => selectGroup(group)} aria-label={`Focus ${group.label}`}>
                <strong>{group.label}</strong>
                <small>{group.status}</small>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {run ? (
        <button type="button" className="cortex-run-focus" aria-pressed={focus === runNode?.node_id} onClick={selectCore}>
          Focus {runHeading(run)}
        </button>
      ) : null}
      {selectionDetail ? (
        <dl className="cortex-detail" aria-label="Selected Cortex node">
          <dt>Kind</dt><dd>{selectionDetail.kind}</dd>
          <dt>Label</dt><dd>{selectionDetail.label}</dd>
          <dt>State</dt><dd>{selectionDetail.state}</dd>
          <dt>Detail</dt><dd className="acc-mono">{selectionDetail.detail}</dd>
        </dl>
      ) : null}
      {nodes.length ? (
        <details className="cortex-atomic-disclosure">
          <summary>All graph nodes ({nodes.length})</summary>
          <ul className="cortex-node-list" aria-label="Cortex nodes">
            {nodes.map((node) => {
              // A grouped satellite can carry the exact same real label as
              // one of its own atomic members (e.g. a "Scout" specialist
              // group and its "Scout" specialist node) -- disambiguate only
              // where that real collision exists, so every other atomic
              // node (the run, a plan step, a tool -- none of which have a
              // same-named group) keeps its plain, already-established name.
              const collidesWithGroup = groups.some((group) => group.label === node.label);
              return (
                <li key={node.node_id}>
                  <button type="button" data-tone={cortexTone(node.state)} data-memory={isMemoryNode(node)} aria-pressed={node.node_id === focus} onClick={() => selectNode(node)} aria-label={collidesWithGroup ? `Focus atomic node ${node.label}` : `Focus ${node.label}`}>
                    {node.label} <small>{isMemoryNode(node) ? "memory" : node.kind.replaceAll("_", " ")} · {node.state}</small>
                  </button>
                </li>
              );
            })}
          </ul>
        </details>
      ) : null}
      <ul className="cortex-legend">
        <li>Running / current</li>
        <li>Recorded evidence</li>
        <li>Blocked or cancelled</li>
      </ul>
    </section>
  );
}

function runHeading(run: AtlasRunResponse): string {
  const state = run.plan.state ?? "ready";
  if (state === "completed") return "Investigation complete";
  if (state === "running") return "Investigation in progress";
  if (state === "failed") return "Investigation failed";
  if (state === "cancelled") return "Investigation cancelled";
  return "Atlas run";
}

const RIM_VERTEX = `
varying vec3 vNormal;
varying vec3 vViewDir;
void main() {
  vNormal = normalize(normalMatrix * normal);
  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  vViewDir = normalize(-mvPosition.xyz);
  gl_Position = projectionMatrix * mvPosition;
}`;
const RIM_FRAGMENT = `
uniform vec3 uColor;
uniform float uIntensity;
varying vec3 vNormal;
varying vec3 vViewDir;
void main() {
  float rim = 1.0 - max(dot(normalize(vNormal), normalize(vViewDir)), 0.0);
  float glow = pow(rim, 2.1) * uIntensity;
  gl_FragColor = vec4(uColor, glow);
}`;

/** The central core: a dense wireframe filament sphere plus a translucent
 * fill and a fresnel-style edge-light shell (cheap, self-contained GLSL --
 * no postprocessing dependency). An idle "breath" always plays (ambient
 * only, never implying thinking); a real running plan raises its pulse
 * rate and glow intensity -- the one and only activity signal. */
function CortexCore({ active, reducedMotion, selected, onClick }: { active: boolean; reducedMotion: boolean; selected: boolean; onClick(): void }) {
  const wireframe = useRef<Mesh>(null);
  const rim = useRef<Mesh>(null);
  const clock = useRef(0);
  const rimMaterial = useMemo(() => new ShaderMaterial({
    uniforms: { uColor: { value: new Color(CORE_COLOR) }, uIntensity: { value: 0.55 } },
    vertexShader: RIM_VERTEX,
    fragmentShader: RIM_FRAGMENT,
    transparent: true,
    depthWrite: false,
    blending: AdditiveBlending,
  }), []);
  useEffect(() => () => rimMaterial.dispose(), [rimMaterial]);
  useFrame((_, delta) => {
    if (reducedMotion) return;
    clock.current += delta;
    const rate = active ? 2.4 : 0.55;
    const amplitude = active ? 0.08 : 0.045;
    const scale = 1 + Math.sin(clock.current * rate) * amplitude;
    if (wireframe.current) { wireframe.current.scale.setScalar(scale); wireframe.current.rotation.y += delta * 0.06; }
    if (rim.current) rim.current.scale.setScalar(scale * 1.02);
    rimMaterial.uniforms.uIntensity!.value = active ? 0.85 + Math.sin(clock.current * rate) * 0.12 : 0.4 + Math.sin(clock.current * rate) * 0.08;
  });
  const color = active ? CORE_COLOR : "#89b8c4";
  return (
    <group onClick={(event) => { event.stopPropagation(); onClick(); }}>
      <mesh ref={wireframe}>
        <sphereGeometry args={[0.95, 40, 28]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={active ? 0.55 : 0.32} />
      </mesh>
      <mesh>
        <sphereGeometry args={[0.9, 24, 18]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={active ? 0.7 : 0.28} transparent opacity={0.14} roughness={0.4} metalness={0.1} />
      </mesh>
      <CoreRibbons color={color} reducedMotion={reducedMotion} active={active} />
      <mesh ref={rim} material={rimMaterial}>
        <sphereGeometry args={[0.97, 32, 24]} />
      </mesh>
      {selected ? <mesh scale={1.45}><icosahedronGeometry args={[0.85, 0]} /><meshBasicMaterial color={color} wireframe transparent opacity={0.4} /></mesh> : null}
    </group>
  );
}

/** A few internal luminous ribbon arcs -- static great-circle-like curves
 * at fixed rotations, purely decorative material detail (never a semantic
 * node or event path). */
function CoreRibbons({ color, reducedMotion, active }: { color: string; reducedMotion: boolean; active: boolean }) {
  const group = useRef<Group>(null);
  const ribbons = useMemo(() => {
    const tilts: [number, number, number][] = [[0.3, 0.9, 0], [1.1, 0, 0.4], [0.6, -0.7, 0.9]];
    return tilts.map((tilt) => {
      const points: Vec3[] = [];
      const segments = 64;
      for (let i = 0; i <= segments; i += 1) {
        const angle = (i / segments) * Math.PI * 2;
        points.push([Math.cos(angle) * 0.82, Math.sin(angle) * 0.82 * 0.4, Math.sin(angle) * 0.3]);
      }
      return { tilt, points };
    });
  }, []);
  useFrame((_, delta) => {
    if (reducedMotion || !group.current) return;
    group.current.rotation.y += delta * (active ? 0.05 : 0.02);
  });
  return (
    <group ref={group}>
      {ribbons.map((ribbon, index) => (
        <group key={index} rotation={ribbon.tilt}>
          <Line points={ribbon.points as unknown as [number, number, number][]} color={color} transparent opacity={active ? 0.5 : 0.3} lineWidth={1.2} />
        </group>
      ))}
    </group>
  );
}

/** Two thin, tilted, purely decorative orbital rings -- ambient material
 * detail, distinct from any semantic node or edge. Static tilt plus
 * perspective (rather than a live camera-relative shader) approximates the
 * front/back depth cue described in the design brief; see the handoff
 * report for that simplification. */
function CortexRing({ radius, tiltX, tiltZ, opacity, reducedMotion, speed }: { radius: number; tiltX: number; tiltZ: number; opacity: number; reducedMotion: boolean; speed: number }) {
  const group = useRef<Group>(null);
  const points = useMemo(() => {
    const segments = 96;
    const result: Vec3[] = [];
    for (let i = 0; i <= segments; i += 1) {
      const angle = (i / segments) * Math.PI * 2;
      result.push([Math.cos(angle) * radius, 0, Math.sin(angle) * radius]);
    }
    return result;
  }, [radius]);
  useFrame((_, delta) => {
    if (reducedMotion || !group.current) return;
    group.current.rotation.z += delta * speed;
  });
  return (
    <group ref={group} rotation={[tiltX, 0, tiltZ]}>
      <Line points={points as unknown as [number, number, number][]} color="#57ddf5" transparent opacity={opacity} lineWidth={1} />
    </group>
  );
}

const PARTICLE_COUNT = 180;

/** Sparse surface particles, bounded in number and rendered as a single
 * Points object (one geometry/material pair, not one mesh each) -- material
 * detail only, never simulated activity trails on an idle or completed run. */
function CortexParticles({ reducedMotion, active }: { reducedMotion: boolean; active: boolean }) {
  const points = useRef<Group>(null);
  const positions = useMemo(() => {
    const array = new Float32Array(PARTICLE_COUNT * 3);
    for (let i = 0; i < PARTICLE_COUNT; i += 1) {
      const radius = 1.05 + Math.random() * 0.35;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      array[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      array[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      array[i * 3 + 2] = radius * Math.cos(phi);
    }
    return array;
  }, []);
  useFrame((_, delta) => {
    if (reducedMotion || !points.current) return;
    points.current.rotation.y += delta * (active ? 0.04 : 0.015);
  });
  return (
    <group ref={points}>
      <points>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        </bufferGeometry>
        <pointsMaterial color="#bdf3fc" size={0.018} sizeAttenuation transparent opacity={0.55} />
      </points>
    </group>
  );
}

const GROUP_GEOMETRY: Record<CortexGroup["kind"], ReactNode> = {
  dataset: <boxGeometry args={[0.42, 0.42, 0.42]} />,
  specialist: <octahedronGeometry args={[0.3, 0]} />,
  evidence: <cylinderGeometry args={[0.26, 0.26, 0.14, 20]} />,
};

function CortexGroupSatellite({ group, position, muted, selected, reducedMotion, onClick }: { group: CortexGroup; position: Vec3; muted: boolean; selected: boolean; reducedMotion: boolean; onClick(): void }) {
  const mesh = useRef<Mesh>(null);
  const color = TONE_COLOR[group.tone];
  const clock = useRef(Math.random() * Math.PI * 2); // phase offset only, never affects position -- purely visual desync so satellites don't pulse in lockstep
  useFrame((_, delta) => {
    if (reducedMotion || group.tone !== "active") return;
    clock.current += delta;
    const scale = 1 + Math.sin(clock.current * 3) * 0.14;
    if (mesh.current) mesh.current.scale.setScalar(scale);
  });
  return (
    <group position={position as unknown as [number, number, number]}>
      <mesh ref={mesh} onClick={(event) => { event.stopPropagation(); onClick(); }}>
        {GROUP_GEOMETRY[group.kind]}
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={muted ? 0.08 : selected ? 0.95 : 0.45} transparent opacity={muted ? 0.22 : 1} roughness={0.35} metalness={0.15} wireframe={group.kind === "dataset"} />
      </mesh>
      {selected ? <mesh scale={1.55}>{GROUP_GEOMETRY[group.kind]}<meshBasicMaterial color={color} wireframe transparent opacity={0.5} /></mesh> : null}
      <Html center distanceFactor={8} occlude={false} className="cortex-label-anchor" style={{ pointerEvents: "none" }}>
        <div className={`cortex-group-label${muted ? " is-muted" : ""}${selected ? " is-selected" : ""}`} data-tone={group.tone}>
          <strong>{group.label}</strong>
          <small>{group.status}</small>
        </div>
      </Html>
    </group>
  );
}

function CortexGroupConnection({ a, b, tone, muted, active, reducedMotion, weight }: { a: Vec3; b: Vec3; tone: CortexTone; muted: boolean; active: boolean; reducedMotion: boolean; weight: number }) {
  const group = useRef<Group>(null);
  const points = useMemo(() => [a, b] as [Vec3, Vec3], [a, b]);
  const color = TONE_COLOR[tone];
  useFrame(({ clock: sceneClock }) => {
    if (reducedMotion || !active || muted || !group.current) return;
    const material = (group.current.children[0] as unknown as { material?: { dashOffset: number } })?.material;
    if (material) material.dashOffset = -sceneClock.getElapsedTime() * 1.1;
  });
  // More real aggregated relations behind this one drawn line read as a
  // very slightly heavier stroke -- a truthful nuance, not a fabricated
  // metric: `weight` is exactly `group.memberEdgeIds.length`.
  const lineWidth = Math.min(2.2, 1 + weight * 0.08);
  return (
    <group ref={group}>
      <Line points={points as unknown as [number, number, number][]} color={color} transparent opacity={muted ? 0.08 : active ? 0.6 : 0.32} lineWidth={lineWidth} dashed={active} dashSize={0.18} gapSize={0.12} />
    </group>
  );
}
