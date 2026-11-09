"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

type DependencyGraphResponse = components["schemas"]["DependencyGraphResponse"];
type GraphNode = components["schemas"]["GraphNode"];

async function fetchGraph(id: string): Promise<DependencyGraphResponse> {
  return apiFetch(`/modules/${id}/graph`);
}

const RELATION_COLORS: Record<string, string> = {
  depends_on: "#3b82f6",
  overrides: "#a855f7",
  plugins: "#f97316",
};

const SIZE = 640;
const CENTER = SIZE / 2;
const RADIUS = 230;
// Beyond this, nodes placed evenly around the circle start overlapping and the
// graph becomes unreadable — a real module in this project's own test fleet
// (Magento_Backend) has 50+ dependents. The rest still reach every module,
// just as a plain list below the graph instead of crammed onto it.
const MAX_CIRCLE_NODES = 16;

function layout(centerId: string, neighbors: GraphNode[]): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {
    [centerId]: { x: CENTER, y: CENTER },
  };
  neighbors.forEach((n, i) => {
    const angle = (i * 2 * Math.PI) / Math.max(neighbors.length, 1) - Math.PI / 2;
    positions[n.id] = {
      x: CENTER + RADIUS * Math.cos(angle),
      y: CENTER + RADIUS * Math.sin(angle),
    };
  });
  return positions;
}

export default function GraphClient({ id }: { id: string }) {
  const router = useRouter();
  const [showOverflow, setShowOverflow] = useState(false);

  const graphQuery = useQuery({ queryKey: ["module-graph", id], queryFn: () => fetchGraph(id) });

  const centerId = graphQuery.data ? `module:${graphQuery.data.center_module_id}` : "";
  const allNeighbors = useMemo(
    () => (graphQuery.data ? graphQuery.data.nodes.filter((n) => n.id !== centerId) : []),
    [graphQuery.data, centerId],
  );
  const visibleNeighbors = allNeighbors.slice(0, MAX_CIRCLE_NODES);
  const overflowNeighbors = allNeighbors.slice(MAX_CIRCLE_NODES);
  const positions = useMemo(
    () => (graphQuery.data ? layout(centerId, visibleNeighbors) : {}),
    [graphQuery.data, centerId, visibleNeighbors],
  );

  return (
    <div className="flex flex-col flex-1 gap-4 p-8 max-w-4xl mx-auto w-full" suppressHydrationWarning>
      {/* suppressHydrationWarning above: see app/modules/page.tsx's own
          top-level div for the full explanation -- the onboarding wizard's
          first-visit dialog marks this div inert via a direct DOM write
          Next's hydration-diff otherwise flags as a false mismatch. */}
      <Link href={`/modules/${id}`} className="text-sm text-primary hover:underline self-start">
        ← Module details
      </Link>

      {graphQuery.isLoading && <p>Loading...</p>}
      {graphQuery.isError && <p className="text-destructive">Failed to load dependency graph.</p>}

      {graphQuery.data && (
        <>
          <h1 className="text-2xl font-semibold tracking-tight">
            {graphQuery.data.center_label} — dependency graph
          </h1>

          <div className="relative mx-auto" style={{ width: SIZE, height: SIZE }}>
            <svg width={SIZE} height={SIZE} className="absolute inset-0" aria-hidden="true">
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
                const from = positions[edge.source];
                const to = positions[edge.target];
                if (!from || !to) return null;
                const color = RELATION_COLORS[edge.relation] ?? "#71717a";
                return (
                  <line
                    key={i}
                    x1={from.x}
                    y1={from.y}
                    x2={to.x}
                    y2={to.y}
                    stroke={color}
                    strokeWidth={1.5}
                    markerEnd={`url(#arrow-${edge.relation})`}
                  />
                );
              })}
            </svg>

            {graphQuery.data.nodes.map((node) => {
              const pos = positions[node.id];
              if (!pos) return null;
              const isCenter = node.id === centerId;
              const clickable = node.kind === "module" && node.module_id !== null && !isCenter;
              const nodeClasses = isCenter
                ? "bg-primary text-primary-foreground border-primary"
                : node.kind === "external"
                  ? "bg-muted text-muted-foreground border-dashed border-border"
                  : "bg-card text-foreground border-border hover:bg-accent/40";

              const content = (
                <div
                  className={`rounded-lg border px-2 py-1 text-xs font-mono text-center max-w-[150px] truncate ${nodeClasses} ${clickable ? "cursor-pointer" : ""}`}
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
                    style={{ left: pos.x, top: pos.y, transform: "translate(-50%, -50%)" }}
                    onClick={navigate}
                    aria-label={`Go to ${node.label}'s dependency graph`}
                  >
                    {content}
                  </button>
                );
              }

              return (
                <div
                  key={node.id}
                  className="absolute"
                  style={{ left: pos.x, top: pos.y, transform: "translate(-50%, -50%)" }}
                >
                  {content}
                </div>
              );
            })}
          </div>

          <div className="flex gap-4 justify-center text-sm text-muted-foreground">
            {Object.entries(RELATION_COLORS).map(([relation, color]) => (
              <span key={relation} className="flex items-center gap-1.5">
                <span className="inline-block w-3 h-0.5" style={{ backgroundColor: color }} />
                {relation.replace("_", " ")}
              </span>
            ))}
          </div>

          {overflowNeighbors.length > 0 && (
            <div className="mx-auto w-full">
              <button
                type="button"
                onClick={() => setShowOverflow((v) => !v)}
                className="text-sm text-primary hover:underline"
              >
                {showOverflow ? "Hide" : "Show"} {overflowNeighbors.length} more{" "}
                {overflowNeighbors.length === 1 ? "dependency" : "dependencies"} (too many to fit on the graph)
              </button>
              {showOverflow && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {overflowNeighbors.map((node) => {
                    const clickable = node.kind === "module" && node.module_id !== null;
                    return clickable ? (
                      <Link
                        key={node.id}
                        href={`/modules/${node.module_id}/graph`}
                        className="rounded-lg border border-border bg-card px-2 py-1 text-xs font-mono hover:bg-accent/40"
                        title={node.label}
                      >
                        {node.label}
                      </Link>
                    ) : (
                      <span
                        key={node.id}
                        className="rounded-lg border border-dashed border-border bg-muted px-2 py-1 text-xs font-mono text-muted-foreground"
                        title={node.label}
                      >
                        {node.label}
                      </span>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
