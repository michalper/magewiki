"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from "d3-force";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import type { components } from "@/lib/api-types";

type DependencyGraphResponse = components["schemas"]["DependencyGraphResponse"];
type GraphNode = components["schemas"]["GraphNode"];
type GraphEdge = components["schemas"]["GraphEdge"];

async function fetchGraph(id: string, depth: number): Promise<DependencyGraphResponse> {
  return apiFetch(`/modules/${id}/graph?depth=${depth}`);
}

const RELATION_COLORS: Record<string, string> = {
  depends_on: "#3b82f6",
  overrides: "#a855f7",
  plugins: "#f97316",
};

const DEPTH_OPTIONS = [1, 2, 3] as const;

// Every node renders at this fixed width, wrapped across as many lines as the
// label needs (see the module-list polish that motivated this: a single-line
// truncated label is useless once two sibling modules share a long prefix).
// These constants approximate that rendered box size well enough to size a
// force-simulation collision radius per node -- not pixel-exact, but close
// enough that boxes stop overlapping, which an exact DOM measurement pass
// isn't worth the complexity for.
const BOX_WIDTH = 170;
const CHARS_PER_LINE = 21;
const LINE_HEIGHT = 16;
const BOX_VERTICAL_PADDING = 10;
const CANVAS_PADDING = 80;
const MIN_CANVAS_SIZE = 500;
const SIMULATION_TICKS = 300;

function estimateNodeRadius(label: string): number {
  const lines = Math.max(1, Math.ceil(label.length / CHARS_PER_LINE));
  const height = lines * LINE_HEIGHT + BOX_VERTICAL_PADDING;
  return Math.hypot(BOX_WIDTH / 2, height / 2) + 8;
}

type SimNode = GraphNode & { x: number; y: number; fx?: number | null; fy?: number | null };
type SimLink = { source: string; target: string; relation: string };

/** Force-directed layout: nodes repel each other and collide-avoid based on
 * their own estimated box size, edges pull connected nodes together, and the
 * center module is pinned at the origin. Replaces an earlier fixed-radius
 * circle layout, which only ever worked for a single ring of direct
 * neighbors and had no way to avoid overlap once boxes wrapped across
 * multiple lines -- see the module graph's own "dopracować" feedback.
 * Deterministic given the same input (no reliance on Math.random for
 * placement): simNodes always start at (0, 0) and the simulation always runs
 * the same fixed tick count, so ordering/shape only ever depends on the
 * nodes/edges themselves.
 */
function layoutNodes(
  nodes: GraphNode[],
  edges: GraphEdge[],
  centerId: string
): Map<string, { x: number; y: number }> {
  const simNodes: SimNode[] = nodes.map((n) => ({ ...n, x: 0, y: 0 }));
  // d3-force's forceLink throws on a link referencing a node id it doesn't
  // know about -- the edges[] the backend returns always reference nodes it
  // also returned (see get_module_dependency_graph's own invariant), but
  // filtering defensively here is cheap and keeps a malformed/stale response
  // from crashing the whole page instead of just dropping that one edge.
  const nodeIds = new Set(nodes.map((n) => n.id));
  const simLinks: SimLink[] = edges
    .filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
    .map((e) => ({ source: e.source, target: e.target, relation: e.relation }));

  const center = simNodes.find((n) => n.id === centerId);
  if (center) {
    center.fx = 0;
    center.fy = 0;
  }

  const simulation = forceSimulation(simNodes)
    .force(
      "link",
      forceLink<SimNode, SimLink>(simLinks)
        .id((d) => d.id)
        .distance(110)
        .strength(0.45)
    )
    // distanceMax keeps two far-apart nodes from still shoving each other
    // further away -- without it, a wide star (one center, many leaves that
    // never link to each other) just keeps spreading for the whole
    // simulation, since nothing else pulls it back in except the weak x/y
    // centering below.
    .force("charge", forceManyBody().strength(-180).distanceMax(300))
    .force(
      "collide",
      forceCollide<SimNode>()
        .radius((d) => estimateNodeRadius(d.label))
        .iterations(3)
    )
    .force("center", forceCenter(0, 0))
    .force("x", forceX(0).strength(0.08))
    .force("y", forceY(0).strength(0.08))
    .stop();

  for (let i = 0; i < SIMULATION_TICKS; i++) simulation.tick();

  const positions = new Map<string, { x: number; y: number }>();
  for (const n of simNodes) positions.set(n.id, { x: n.x, y: n.y });
  return positions;
}

function computeCanvas(nodes: GraphNode[], positions: Map<string, { x: number; y: number }>) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  // positions is always built from this exact `nodes` array one entry at a
  // time (layoutNodes' own simNodes = nodes.map(...)), so every node here
  // always has a position -- no "missing position" guard needed.
  for (const n of nodes) {
    const p = positions.get(n.id) as { x: number; y: number };
    const r = estimateNodeRadius(n.label);
    minX = Math.min(minX, p.x - r);
    maxX = Math.max(maxX, p.x + r);
    minY = Math.min(minY, p.y - r);
    maxY = Math.max(maxY, p.y + r);
  }
  if (!Number.isFinite(minX)) {
    minX = minY = maxX = maxY = 0;
  }
  const width = Math.max(MIN_CANVAS_SIZE, maxX - minX + CANVAS_PADDING * 2);
  const height = Math.max(MIN_CANVAS_SIZE, maxY - minY + CANVAS_PADDING * 2);
  const offsetX = CANVAS_PADDING - minX;
  const offsetY = CANVAS_PADDING - minY;
  return { width, height, offsetX, offsetY };
}

export default function GraphClient({ id }: { id: string }) {
  const router = useRouter();
  const [depth, setDepth] = useState<(typeof DEPTH_OPTIONS)[number]>(1);

  const graphQuery = useQuery({
    queryKey: ["module-graph", id, depth],
    queryFn: () => fetchGraph(id, depth),
  });

  const centerId = graphQuery.data ? `module:${graphQuery.data.center_module_id}` : "";

  const positions = useMemo(
    () => (graphQuery.data ? layoutNodes(graphQuery.data.nodes, graphQuery.data.edges, centerId) : new Map()),
    [graphQuery.data, centerId]
  );
  const canvas = useMemo(
    () => (graphQuery.data ? computeCanvas(graphQuery.data.nodes, positions) : null),
    [graphQuery.data, positions]
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const centerPos = positions.get(centerId);
  const [canScroll, setCanScroll] = useState(false);
  useEffect(() => {
    // The force layout can grow much wider than the viewport (a module with
    // many direct dependents, or any depth > 1) -- without this, the
    // scrollable container just opens at its top-left corner, and the one
    // node the page is actually about may not be on screen at all.
    const el = scrollRef.current;
    if (!el || !canvas || !centerPos) return;
    el.scrollLeft = centerPos.x + canvas.offsetX - el.clientWidth / 2;
    el.scrollTop = centerPos.y + canvas.offsetY - el.clientHeight / 2;
    // Nothing on the page otherwise hints that the graph is pannable -- a
    // wider-than-the-box canvas (common once depth > 1, or a well-connected
    // hub module) previously just clipped nodes at the edges with no
    // scrollbar affordance obvious enough to notice.
    setCanScroll(el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1);
  }, [canvas, centerPos]);

  return (
    <div className="flex flex-col flex-1 gap-4 p-8 max-w-5xl mx-auto w-full" suppressHydrationWarning>
      {/* suppressHydrationWarning above: see app/modules/page.tsx's own
          top-level div for the full explanation -- the onboarding wizard's
          first-visit dialog marks this div inert via a direct DOM write
          Next's hydration-diff otherwise flags as a false mismatch. */}
      <Link href={`/modules/${id}`} className="text-sm text-primary hover:underline self-start">
        ← Module details
      </Link>

      {graphQuery.isLoading && <p>Loading...</p>}
      {graphQuery.isError && <p className="text-destructive">Failed to load dependency graph.</p>}

      {graphQuery.data && canvas && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">
              {graphQuery.data.center_label} — dependency graph
            </h1>
            <div className="flex items-center gap-1.5 text-sm">
              <span className="text-muted-foreground">Depth:</span>
              {DEPTH_OPTIONS.map((d) => (
                <Button
                  key={d}
                  type="button"
                  variant={d === depth ? "default" : "outline"}
                  size="sm"
                  aria-pressed={d === depth}
                  onClick={() => setDepth(d)}
                >
                  {d}
                </Button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
            <span>{graphQuery.data.nodes.length} nodes shown</span>
            {graphQuery.data.truncated && (
              // Depth 2 and depth 3 can render the exact same graph with no
              // visible difference once the backend's node cap is hit at or
              // before the shallower depth -- showing the live node count
              // next to this message lets that be self-evident (same count
              // at both depths) instead of silently mysterious.
              <span>
                — hit the size limit for one graph; some dependencies beyond this aren&apos;t shown. A higher depth
                may not reveal more once the limit is already reached.
              </span>
            )}
            {canScroll && <span>· scroll/drag inside the graph to see the rest</span>}
          </div>

          <div
            ref={scrollRef}
            className="relative mx-auto overflow-auto rounded-2xl border border-border/50"
            style={{ maxWidth: "100%", maxHeight: 720 }}
          >
            <div className="relative" style={{ width: canvas.width, height: canvas.height }}>
              <svg width={canvas.width} height={canvas.height} className="absolute inset-0" aria-hidden="true">
                <defs>
                  {Object.entries(RELATION_COLORS).map(([relation, color]) => (
                    <marker
                      key={relation}
                      id={`arrow-${relation}`}
                      viewBox="0 0 10 10"
                      refX="9"
                      refY="5"
                      markerWidth="6"
                      markerHeight="6"
                      orient="auto-start-reverse"
                    >
                      <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
                    </marker>
                  ))}
                </defs>
                {graphQuery.data.edges.map((edge, i) => {
                  const from = positions.get(edge.source);
                  const to = positions.get(edge.target);
                  if (!from || !to) return null;
                  const color = RELATION_COLORS[edge.relation] ?? "#71717a";
                  return (
                    <line
                      key={i}
                      x1={from.x + canvas.offsetX}
                      y1={from.y + canvas.offsetY}
                      x2={to.x + canvas.offsetX}
                      y2={to.y + canvas.offsetY}
                      stroke={color}
                      strokeWidth={1.5}
                      markerEnd={`url(#arrow-${edge.relation})`}
                    />
                  );
                })}
              </svg>

              {graphQuery.data.nodes.map((node) => {
                // Same guaranteed 1:1 correspondence as computeCanvas's own
                // positions lookup above -- every node here always has one.
                const pos = positions.get(node.id) as { x: number; y: number };
                const left = pos.x + canvas.offsetX;
                const top = pos.y + canvas.offsetY;
                const isCenter = node.id === centerId;
                const clickable = node.kind === "module" && node.module_id !== null && !isCenter;
                const nodeClasses = isCenter
                  ? "bg-primary text-primary-foreground border-primary"
                  : node.kind === "external"
                    ? "bg-muted text-muted-foreground border-dashed border-border"
                    : "bg-card text-foreground border-border hover:bg-accent/40";

                const content = (
                  // w-[170px] + whitespace-normal/break-words (not truncate):
                  // the full label always renders on the node itself, not
                  // only via the title tooltip on hover.
                  <div
                    className={`rounded-lg border px-2 py-1 text-xs font-mono text-center w-[170px] whitespace-normal break-words ${nodeClasses} ${clickable ? "cursor-pointer" : ""}`}
                    title={node.label}
                  >
                    {node.label}
                  </div>
                );
                const navigate = () => router.push(`/modules/${node.module_id}/graph`);

                if (clickable) {
                  return (
                    <button
                      key={node.id}
                      type="button"
                      className="absolute appearance-none border-0 bg-transparent p-0 rounded-lg focus-visible:outline-2 focus-visible:outline-ring"
                      style={{ left, top, transform: "translate(-50%, -50%)" }}
                      onClick={navigate}
                      aria-label={`Go to ${node.label}'s dependency graph`}
                    >
                      {content}
                    </button>
                  );
                }

                return (
                  <div key={node.id} className="absolute" style={{ left, top, transform: "translate(-50%, -50%)" }}>
                    {content}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="flex gap-4 justify-center text-sm text-muted-foreground">
            {Object.entries(RELATION_COLORS).map(([relation, color]) => (
              <span key={relation} className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-0.5" style={{ backgroundColor: color }} />
                {relation.replace("_", " ")}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
