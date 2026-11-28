"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useChartPalette } from "@/components/chart-palette";
import { sumFindingCounts } from "@/components/quality-badges";
import {
  Tooltip as InfoTooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { apiFetch } from "@/lib/api";
import type { components, paths } from "@/lib/api-types";
import { FALLBACK_CHECK_TYPES, KPI_TILES, prettifyCheckType } from "@/lib/kpi-tiles";
import { useDocumentTitle } from "@/lib/use-document-title";
import { useMediaQuery } from "@/lib/use-media-query";

type ModuleSummary = components["schemas"]["ModuleSummary"];
type FleetTrendPoint =
  paths["/modules/history/trend"]["get"]["responses"][200]["content"]["application/json"][number];
type LlmSpendTrend =
  paths["/settings/llm/spend-trend"]["get"]["responses"][200]["content"]["application/json"];

// Fixed display order/labels for AnalysisCache.kind's 6 CHECK-constrained
// values (app/models.py's ck_analysis_cache_kind) -- a plain lookup, not
// prettifyCheckType, since this is a small, fixed enum rather than an
// open-ended check_type vocabulary.
const KIND_LABELS: Record<string, string> = {
  file_summary: "File summaries",
  module_synthesis: "Module synthesis",
  embedding: "Embeddings",
  chat: "Chat",
  rerank: "Rerank",
  query_rewrite: "Query rewrite",
};

function sumByCheckType(modules: ModuleSummary[], checkType: string): number {
  return modules.reduce((sum, m) => sum + (m.finding_counts[checkType] ?? 0), 0);
}

async function fetchModules(): Promise<ModuleSummary[]> {
  const response = await apiFetch<components["schemas"]["ModuleListResponse"]>("/modules");
  return response.modules;
}

async function fetchFleetTrend(): Promise<FleetTrendPoint[]> {
  return apiFetch("/modules/history/trend");
}

async function fetchLlmSpendTrend(): Promise<LlmSpendTrend> {
  return apiFetch("/settings/llm/spend-trend");
}

function StatTile({
  label,
  value,
  accent,
  description,
  findingTypes,
}: {
  label: string;
  value: number | string;
  accent?: string;
  description?: string;
  // Check type key(s) this tile sums — when set, the tile links to the
  // Modules list pre-filtered to exactly the modules counted here.
  findingTypes?: string[];
}) {
  const className = "flex flex-col gap-1 rounded-2xl bg-card p-5 shadow-sm";
  const style = accent ? { borderLeftColor: accent, borderLeftWidth: 3 } : undefined;

  if (findingTypes && findingTypes.length > 0 && Number(value) > 0) {
    return (
      <Link
        href={`/modules?finding=${findingTypes.join(",")}`}
        className={`${className} hover:bg-accent/40 transition-colors`}
        style={style}
      >
        <StatTileBody label={label} value={value} description={description} />
      </Link>
    );
  }

  return (
    <div className={className} style={style}>
      <StatTileBody label={label} value={value} description={description} />
    </div>
  );
}

function StatTileBody({
  label,
  value,
  description,
}: {
  label: string;
  value: number | string;
  description?: string;
}) {
  return (
    <>
      <span className="flex items-center gap-1 text-xs uppercase tracking-wide text-muted-foreground">
        {label}
        {description && (
          <InfoTooltip>
            <TooltipTrigger
              className="inline-flex text-muted-foreground/70 hover:text-foreground"
              aria-label={`What is "${label}"?`}
              onClick={(e) => e.preventDefault()}
            >
              <Info className="size-3" />
            </TooltipTrigger>
            <TooltipContent>{description}</TooltipContent>
          </InfoTooltip>
        )}
      </span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
    </>
  );
}

function ProgressRing({
  label,
  value,
  total,
  color,
}: {
  label: string;
  value: number;
  total: number;
  color: string;
}) {
  const palette = useChartPalette();
  // total === 0 is unreachable today -- StatsPage only renders ProgressRing
  // inside its own "modules.length > 0" block, and total is always that same
  // length -- kept as a guard against this component being reused somewhere
  // that doesn't have that invariant.
  /* v8 ignore next */
  const pct = total === 0 ? 0 : Math.round((value / total) * 100);
  const data = [
    { name: label, value, fill: color },
    { name: "remaining", value: total - value, fill: palette.track },
  ];

  return (
    <div className="flex flex-col items-center gap-2 rounded-2xl bg-card p-5 shadow-sm">
      <div className="relative h-24 w-24">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              innerRadius={32}
              outerRadius={44}
              startAngle={90}
              endAngle={-270}
              stroke="none"
              isAnimationActive={false}
            />
            {/* Per-slice color comes from each data entry's own `fill` field above
                (Recharts' Pie reads it directly) -- <Cell> is deprecated as of
                recharts 3.x, removed in 4.0; see its own JSDoc for the migration
                note this follows. */}
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <span className="text-lg font-semibold">{pct}%</span>
        </div>
      </div>
      <span className="text-sm text-center text-muted-foreground">{label}</span>
    </div>
  );
}

const DESKTOP_AXIS_WIDTH = 210;
const MOBILE_AXIS_WIDTH = 88;
const MOBILE_LABEL_CHARS = 11;

// Truncating from the END would make every one of this project's own module
// names collapse to the same "Magento_…" (same lesson already learned on the
// module list and the dependency graph) -- keep the tail, where Magento
// module names actually differ, instead.
export function truncateLabelTail(label: string, maxChars: number): string {
  if (label.length <= maxChars) return label;
  return `…${label.slice(-(maxChars - 1))}`;
}

// Named instead of inline so it's directly unit-testable -- Recharts never
// actually calls a YAxis tickFormatter in these tests (see the
// truncateLabelTail describe block above), since jsdom's ResponsiveContainer
// never gets real layout dimensions.
export function formatMobileAxisTick(name: string): string {
  return truncateLabelTail(name, MOBILE_LABEL_CHARS);
}

function TopFindingsBar({ modules }: { modules: ModuleSummary[] }) {
  const palette = useChartPalette();
  // A fixed YAxis label column (Recharts needs a real pixel width, not a
  // responsive unit) left almost no room for the bars themselves on a real
  // phone width -- the chart's whole point, comparing magnitude, was lost.
  const isNarrow = useMediaQuery("(max-width: 480px)");
  const data = modules
    .map((m) => ({
      name: m.name,
      total: sumFindingCounts(m.finding_counts),
    }))
    .filter((d) => d.total > 0)
    .sort((a, b) => b.total - a.total)
    .slice(0, 10);

  if (data.length === 0) {
    return (
      <div className="rounded-2xl bg-card p-5 shadow-sm">
        <h3 className="text-sm font-medium mb-2 text-muted-foreground">Top modules by quality findings</h3>
        <p className="text-sm text-muted-foreground">No quality findings across any scanned module.</p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-card p-5 shadow-sm">
      <h3 className="text-sm font-medium mb-2 text-muted-foreground">Top modules by quality findings</h3>
      <p className="text-xs text-muted-foreground mb-2">Log scale — counts span multiple orders of magnitude</p>
      <ResponsiveContainer width="100%" height={Math.max(200, data.length * 32)}>
        <BarChart data={data} layout="vertical" margin={{ left: 24, right: isNarrow ? 20 : 36 }}>
          <CartesianGrid horizontal={false} stroke={palette.ink.gridline} />
          <XAxis
            type="number"
            scale="log"
            domain={[0.9, "auto"]}
            allowDataOverflow
            allowDecimals={false}
            tick={{ fill: palette.ink.muted, fontSize: 12 }}
          />
          <YAxis
            type="category"
            dataKey="name"
            width={isNarrow ? MOBILE_AXIS_WIDTH : DESKTOP_AXIS_WIDTH}
            tickFormatter={isNarrow ? formatMobileAxisTick : undefined}
            tick={{ fill: palette.ink.muted, fontSize: 12 }}
          />
          <Tooltip />
          <Bar dataKey="total" fill={palette.sequential} radius={[0, 4, 4, 0]} maxBarSize={24}>
            <LabelList dataKey="total" position="right" fill={palette.ink.muted} fontSize={12} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function FleetTrendChart({ points }: { points: FleetTrendPoint[] }) {
  const palette = useChartPalette();
  // Phase 22b: module_history_snapshots is deduplicated per module (one row
  // per *change*, not per scan -- app/search/fleet_trend.py carries each
  // module's own last-known total forward), so a brand-new scan with
  // nothing changed since baseline yet has no points at all -- that's the
  // one real, deterministic empty state here, not a transient loading gap.
  if (points.length === 0) {
    return (
      <div className="rounded-2xl bg-card p-5 shadow-sm">
        <h3 className="text-sm font-medium mb-2 text-muted-foreground">
          Total findings across the fleet, over time
        </h3>
        <p className="text-sm text-muted-foreground">
          No history yet — this fills in once a rescan changes something for at least one module.
        </p>
      </div>
    );
  }

  const data = points.map((p) => ({
    scannedAt: p.scanned_at,
    label: new Date(p.scanned_at).toLocaleDateString(),
    total: p.total_findings,
  }));

  return (
    <div className="rounded-2xl bg-card p-5 shadow-sm">
      <h3 className="text-sm font-medium mb-2 text-muted-foreground">
        Total findings across the fleet, over time
      </h3>
      <p className="text-xs text-muted-foreground mb-2">
        Is the fleet as a whole getting better or worse — not just one module&apos;s own history
      </p>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ left: 0, right: 16, top: 8, bottom: 0 }}>
          <CartesianGrid stroke={palette.ink.gridline} />
          <XAxis dataKey="label" tick={{ fill: palette.ink.muted, fontSize: 12 }} />
          <YAxis allowDecimals={false} tick={{ fill: palette.ink.muted, fontSize: 12 }} />
          <Tooltip />
          <Line
            type="monotone"
            dataKey="total"
            stroke={palette.sequential}
            strokeWidth={2}
            dot={{ r: 3, fill: palette.sequential }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

const OTHER_CATEGORY_LABEL = "Other";

function categoryTotal(counts: Record<string, number>, checkTypes: string[]): number {
  return checkTypes.reduce((sum, ct) => sum + (counts[ct] ?? 0), 0);
}

// Named/exported so it's directly unit-testable without going through
// Recharts (same reasoning as pivotSpendByDay below). Folds each point's raw
// per-check_type counts into lib/kpi-tiles.ts's already-curated KPI_TILES
// categories (plus one "Other" bucket for anything FALLBACK_CHECK_TYPES
// still doesn't have a tile for) instead of a raw, noisy per-check_type
// series -- the same category language the KPI tile grid above already
// uses. Categories that are 0 across the whole series are dropped, same
// filtering spirit as TopFindingsBar's own `.filter(d => d.total > 0)`.
export function groupFleetTrendByCategory(points: FleetTrendPoint[]): {
  rows: Record<string, number | string>[];
  categories: string[];
} {
  const categoryDefs = [
    ...KPI_TILES.map((tile) => ({ label: tile.label, checkTypes: tile.checkTypes })),
    { label: OTHER_CATEGORY_LABEL, checkTypes: FALLBACK_CHECK_TYPES },
  ];

  const rows = points.map((p) => {
    const row: Record<string, number | string> = { label: new Date(p.scanned_at).toLocaleDateString() };
    for (const def of categoryDefs) {
      row[def.label] = categoryTotal(p.counts, def.checkTypes);
    }
    return row;
  });

  const categories = categoryDefs
    .map((def) => def.label)
    .filter((label) => rows.some((row) => Number(row[label]) > 0));

  return { rows, categories };
}

function FleetTrendByCategoryChart({ points }: { points: FleetTrendPoint[] }) {
  const palette = useChartPalette();

  if (points.length === 0) {
    return (
      <div className="rounded-2xl bg-card p-5 shadow-sm">
        <h3 className="text-sm font-medium mb-2 text-muted-foreground">Findings trend by category</h3>
        <p className="text-sm text-muted-foreground">
          No category history yet — this fills in once a rescan changes something for at least one module.
        </p>
      </div>
    );
  }

  const { rows, categories } = groupFleetTrendByCategory(points);

  if (categories.length === 0) {
    return (
      <div className="rounded-2xl bg-card p-5 shadow-sm">
        <h3 className="text-sm font-medium mb-2 text-muted-foreground">Findings trend by category</h3>
        <p className="text-sm text-muted-foreground">No findings in any category yet.</p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-card p-5 shadow-sm">
      <h3 className="text-sm font-medium mb-2 text-muted-foreground">Findings trend by category</h3>
      <p className="text-xs text-muted-foreground mb-2">
        Which category is driving the fleet-wide total up or down
      </p>
      <ResponsiveContainer width="100%" height={240}>
        <AreaChart data={rows} margin={{ left: 0, right: 16, top: 8, bottom: 0 }}>
          <CartesianGrid stroke={palette.ink.gridline} />
          <XAxis dataKey="label" tick={{ fill: palette.ink.muted, fontSize: 12 }} />
          <YAxis allowDecimals={false} tick={{ fill: palette.ink.muted, fontSize: 12 }} />
          <Tooltip />
          {categories.map((category, i) => (
            <Area
              key={category}
              dataKey={category}
              name={category}
              stackId="trend"
              stroke={palette.categorical[i % palette.categorical.length]}
              fill={palette.categorical[i % palette.categorical.length]}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

type LlmSpendPoint = LlmSpendTrend["points"][number];

// Named/exported so it's directly unit-testable without going through
// Recharts -- same reasoning as formatMobileAxisTick above (jsdom's
// ResponsiveContainer never gives Recharts real layout, so a dataKey render
// path never actually runs in these tests). Pivots day+kind rows into one
// row per day with each present kind as its own numeric field, which is
// what a stacked BarChart needs -- one <Bar dataKey={kind}> per series.
export function pivotSpendByDay(points: LlmSpendPoint[]): { label: string; day: string; kinds: Record<string, number> }[] {
  const byDay = new Map<string, { label: string; day: string; kinds: Record<string, number> }>();
  for (const p of points) {
    const row = byDay.get(p.day) ?? {
      label: new Date(p.day).toLocaleDateString(),
      day: p.day,
      kinds: {},
    };
    row.kinds[p.kind] = (row.kinds[p.kind] ?? 0) + Number(p.cost_usd);
    byDay.set(p.day, row);
  }
  return [...byDay.values()].sort((a, b) => a.day.localeCompare(b.day));
}

// Named/exported for the same reason as formatMobileAxisTick above -- a
// Recharts tickFormatter/Tooltip formatter never actually runs in these
// tests (jsdom's ResponsiveContainer never gets real layout).
export function formatSpendAxisTick(value: number): string {
  return `$${value}`;
}

export function formatSpendTooltip(value: unknown): string {
  return `$${Number(value).toFixed(4)}`;
}

function LlmSpendByKindChart({ points }: { points: LlmSpendPoint[] }) {
  const palette = useChartPalette();

  if (points.length === 0) {
    return (
      <div className="rounded-2xl bg-card p-5 shadow-sm">
        <h3 className="text-sm font-medium mb-2 text-muted-foreground">LLM spend this month, by kind</h3>
        <p className="text-sm text-muted-foreground">
          No LLM calls yet this month — this fills in once analysis, embedding, or chat calls happen.
        </p>
      </div>
    );
  }

  const rows = pivotSpendByDay(points);
  const kinds = [...new Set(points.map((p) => p.kind))];
  const data = rows.map((row) => ({ label: row.label, ...row.kinds }));

  return (
    <div className="rounded-2xl bg-card p-5 shadow-sm">
      <h3 className="text-sm font-medium mb-2 text-muted-foreground">LLM spend this month, by kind</h3>
      <p className="text-xs text-muted-foreground mb-2">
        Where this month&apos;s budget went — analysis, embedding, chat, rerank, and query-rewrite calls
      </p>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ left: 0, right: 16, top: 8, bottom: 0 }}>
          <CartesianGrid stroke={palette.ink.gridline} />
          <XAxis dataKey="label" tick={{ fill: palette.ink.muted, fontSize: 12 }} />
          <YAxis
            allowDecimals
            tickFormatter={formatSpendAxisTick}
            tick={{ fill: palette.ink.muted, fontSize: 12 }}
          />
          <Tooltip formatter={formatSpendTooltip} />
          {kinds.map((kind, i) => (
            <Bar
              key={kind}
              dataKey={kind}
              name={KIND_LABELS[kind] ?? kind}
              stackId="spend"
              fill={palette.categorical[i % palette.categorical.length]}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function StatsPage() {
  useDocumentTitle("Stats");
  const modulesQuery = useQuery({ queryKey: ["modules"], queryFn: fetchModules });
  const fleetTrendQuery = useQuery({ queryKey: ["fleet-trend"], queryFn: fetchFleetTrend });
  const llmSpendQuery = useQuery({ queryKey: ["llm-spend-trend"], queryFn: fetchLlmSpendTrend });
  const palette = useChartPalette();
  const modules = useMemo(() => modulesQuery.data ?? [], [modulesQuery.data]);
  const fleetTrend = useMemo(() => fleetTrendQuery.data ?? [], [fleetTrendQuery.data]);

  const spentUsd = llmSpendQuery.data ? Number(llmSpendQuery.data.total_spent_usd) : 0;
  const budgetUsd = llmSpendQuery.data?.monthly_budget_usd ?? 0;
  const spendPct = budgetUsd > 0 ? Math.round((spentUsd / budgetUsd) * 100) : 0;
  const spendRingColor =
    spendPct >= 100 ? palette.status.critical : spendPct >= 75 ? palette.status.warning : palette.status.good;

  const totals = useMemo(
    () => ({
      total: modules.length,
      withReadme: modules.filter((m) => m.has_readme).length,
      withTests: modules.filter((m) => m.has_tests).length,
      withModuleDoc: modules.filter((m) => m.has_module_doc).length,
    }),
    [modules]
  );

  const kpiTiles = useMemo(
    () =>
      KPI_TILES.map((tile) => ({
        ...tile,
        value: tile.checkTypes.reduce((sum, ct) => sum + sumByCheckType(modules, ct), 0),
      })),
    [modules]
  );

  // Every check_type CHECK_TYPES knows about that no KPI_TILES entry claims --
  // a plain tile with a prettified label instead of silently having no Stats
  // representation at all. Empty today (every real check_type already has a
  // curated tile above); exists so the NEXT one added without updating this
  // file still shows up somewhere.
  const fallbackTiles = useMemo(
    () =>
      FALLBACK_CHECK_TYPES.map((checkType) => ({
        label: prettifyCheckType(checkType),
        checkTypes: [checkType],
        accent: "warning" as const,
        description: undefined,
        value: sumByCheckType(modules, checkType),
      })),
    [modules]
  );

  return (
    <TooltipProvider>
    {/* suppressHydrationWarning: see app/modules/page.tsx's own top-level
        div for the full explanation -- the onboarding wizard's first-visit
        dialog marks this div inert via a direct DOM write Next's
        hydration-diff otherwise flags as a false mismatch. */}
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-5xl mx-auto w-full" suppressHydrationWarning>
      <h1 className="text-2xl font-semibold tracking-tight">Stats</h1>

      {modulesQuery.isLoading && <p>Loading...</p>}
      {modulesQuery.isError && <p className="text-destructive">Failed to load modules.</p>}

      {modulesQuery.data && modules.length === 0 && (
        <p className="text-muted-foreground">No modules scanned yet.</p>
      )}

      {modulesQuery.data && modules.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatTile label="Modules scanned" value={totals.total} />
            {[...kpiTiles, ...fallbackTiles].map((tile) => (
              <StatTile
                key={tile.label}
                label={tile.label}
                value={tile.value}
                accent={tile.accent !== "none" && tile.value > 0 ? palette.status[tile.accent] : undefined}
                description={tile.description}
                findingTypes={tile.checkTypes}
              />
            ))}
          </div>

          <div className="flex flex-wrap gap-4">
            <ProgressRing
              label="Have a README"
              value={totals.withReadme}
              total={totals.total}
              color={palette.status.good}
            />
            <ProgressRing
              label="Have tests"
              value={totals.withTests}
              total={totals.total}
              color={palette.status.good}
            />
            <ProgressRing
              label="Have an AI-generated doc"
              value={totals.withModuleDoc}
              total={totals.total}
              color={palette.status.good}
            />
          </div>

          <TopFindingsBar modules={modules} />
          {fleetTrendQuery.isError ? (
            <p className="text-destructive">Failed to load the fleet history trend.</p>
          ) : (
            <>
              <FleetTrendChart points={fleetTrend} />
              <FleetTrendByCategoryChart points={fleetTrend} />
            </>
          )}

          {llmSpendQuery.isError && (
            <p className="text-destructive">Failed to load LLM spend.</p>
          )}
          {llmSpendQuery.data && (
            <>
              <div className="flex flex-wrap items-center gap-4">
                <ProgressRing
                  label="Of this month's LLM budget"
                  value={Math.min(spentUsd, budgetUsd)}
                  total={budgetUsd}
                  color={spendRingColor}
                />
                <p className="text-sm text-muted-foreground">
                  ${spentUsd.toFixed(2)} of ${budgetUsd.toFixed(2)} spent this month ({spendPct}%)
                </p>
              </div>
              <LlmSpendByKindChart points={llmSpendQuery.data.points} />
            </>
          )}
        </>
      )}
    </div>
    </TooltipProvider>
  );
}
