"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useChartPalette } from "@/components/chart-palette";
import { CHECK_TYPES, sumFindingCounts } from "@/components/quality-badges";
import {
  Tooltip as InfoTooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { apiFetch } from "@/lib/api";
import type { paths } from "@/lib/api-types";
import { useDocumentTitle } from "@/lib/use-document-title";

type ModuleSummary =
  paths["/modules"]["get"]["responses"][200]["content"]["application/json"][number];

function sumByCheckType(modules: ModuleSummary[], checkType: string): number {
  return modules.reduce((sum, m) => sum + (m.finding_counts[checkType] ?? 0), 0);
}

type AccentLevel = "critical" | "warning" | "none";

// The curated, human-written KPI tiles — each names exactly which check_type(s)
// it summarizes (some fold several related ones into one tile, e.g. "Magento
// upgrade blockers" or "Cross-module conflicts"). checkTypes here is the single
// source of truth this page uses to compute every total below AND to figure out
// which check_types still have no tile at all (see FALLBACK_CHECK_TYPES) — a new
// check_type is invisible here only if nobody adds it to one of these arrays,
// which previously happened twice in one session (PhpMetrics, then three more
// check types) before this fallback existed.
const KPI_TILES: {
  label: string;
  checkTypes: string[];
  accent: AccentLevel;
  description: string;
}[] = [
  {
    label: "Hardcoded secrets",
    checkTypes: ["hardcoded_secret"],
    accent: "critical",
    description:
      "API keys, passwords, or tokens written directly in the code instead of a secure config. Anyone with code access can read them — fix urgently.",
  },
  {
    label: "Known vulnerabilities",
    checkTypes: ["security_advisory"],
    accent: "critical",
    description:
      "Third-party libraries with publicly disclosed security flaws (CVEs). Each one cites the advisory it matched.",
  },
  {
    label: "Deprecated usages",
    checkTypes: ["deprecated_annotation"],
    accent: "warning",
    description:
      "Code calling something Magento has marked for removal in a future version — works today, but will need updating before the next major upgrade.",
  },
  {
    label: "Composer issues",
    checkTypes: ["composer_completeness"],
    accent: "warning",
    description:
      "Problems with a module's own packaging metadata (Composer is Magento's package manager) — e.g. missing license info or test coverage declared incorrectly.",
  },
  {
    label: "Abandoned dependencies",
    checkTypes: ["abandoned_dependency"],
    accent: "warning",
    description:
      "Third-party libraries the maintainer has officially stopped supporting — no more fixes or security patches will ever come, even for new vulnerabilities.",
  },
  {
    label: "Outdated dependencies",
    checkTypes: ["outdated_dependency"],
    accent: "none",
    description: "Third-party libraries with a newer version available. Not urgent on its own, but worth tracking so upgrades don't pile up.",
  },
  {
    label: "Magento upgrade blockers",
    checkTypes: ["magento_php_incompatible", "magento_version_blocker"],
    accent: "critical",
    description:
      "Modules that would break outright on the latest Magento release (wrong PHP version or incompatible Magento package requirement) — these block an upgrade project until fixed.",
  },
  {
    label: "PHP static-analysis findings",
    checkTypes: ["phpstan_error", "phpmd_issue", "phpcs_violation", "php_compat_issue", "phpmetrics_issue"],
    accent: "warning",
    description:
      "Code-quality issues caught by automated PHP analysis tools (bugs, style violations, overly complex code, risky metrics) — a proxy for how much technical debt a module carries.",
  },
  {
    label: "Cross-module conflicts",
    checkTypes: [
      "plugin_conflict",
      "composer_conflict",
      "webapi_route_conflict",
      "db_schema_conflict",
      "circular_dependency",
    ],
    accent: "warning",
    description:
      "Two modules silently fighting over the same plugin hook, Composer package version, REST route, or database column — or a circular module.xml sequence that breaks setup:upgrade outright. Each shows up on every module involved.",
  },
  {
    label: "License risks",
    checkTypes: ["license_risk"],
    accent: "warning",
    description:
      "Modules declaring a strong-copyleft license (GPL/AGPL/SSPL) — bundling one into a commercial store may carry real redistribution obligations worth reviewing.",
  },
  {
    label: "PHPUnit test failures",
    checkTypes: ["phpunit_failure"],
    accent: "warning",
    description:
      "Failing tests from a module's own Test/Unit/ suite, actually executed via its own vendor/bin/phpunit — only for modules that ship a standalone-runnable phpunit setup.",
  },
];

const _GROUPED_CHECK_TYPES = new Set(KPI_TILES.flatMap((t) => t.checkTypes));

// Any check_type CHECK_TYPES knows about but no KPI_TILES entry claims gets a
// plain, auto-generated tile instead of silently having no Stats representation
// at all — the actual fix for the bug class above. A new check_type can still get
// a hand-written label/description/grouping by adding it to KPI_TILES like any
// other; this only guarantees it's never invisible before someone does.
const FALLBACK_CHECK_TYPES = CHECK_TYPES.map((c) => c.key).filter((key) => !_GROUPED_CHECK_TYPES.has(key));

function prettifyCheckType(checkType: string): string {
  const words = checkType.split("_").join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

async function fetchModules(): Promise<ModuleSummary[]> {
  return apiFetch("/modules");
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
    { name: label, value },
    { name: "remaining", value: total - value },
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
            >
              <Cell fill={color} />
              <Cell fill={palette.track} />
            </Pie>
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

function TopFindingsBar({ modules }: { modules: ModuleSummary[] }) {
  const palette = useChartPalette();
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
        <BarChart data={data} layout="vertical" margin={{ left: 24, right: 36 }}>
          <CartesianGrid horizontal={false} stroke={palette.ink.gridline} />
          <XAxis
            type="number"
            scale="log"
            domain={[0.9, "auto"]}
            allowDataOverflow
            allowDecimals={false}
            tick={{ fill: palette.ink.muted, fontSize: 12 }}
          />
          <YAxis type="category" dataKey="name" width={210} tick={{ fill: palette.ink.muted, fontSize: 12 }} />
          <Tooltip />
          <Bar dataKey="total" fill={palette.sequential} radius={[0, 4, 4, 0]} maxBarSize={24}>
            <LabelList dataKey="total" position="right" fill={palette.ink.muted} fontSize={12} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function StatsPage() {
  useDocumentTitle("Stats");
  const modulesQuery = useQuery({ queryKey: ["modules"], queryFn: fetchModules });
  const palette = useChartPalette();
  const modules = useMemo(() => modulesQuery.data ?? [], [modulesQuery.data]);

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
        accent: "warning" as AccentLevel,
        description: undefined,
        value: sumByCheckType(modules, checkType),
      })),
    [modules]
  );

  return (
    <TooltipProvider>
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-5xl mx-auto w-full">
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
        </>
      )}
    </div>
    </TooltipProvider>
  );
}
