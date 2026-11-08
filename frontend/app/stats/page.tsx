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
import { sumFindingCounts } from "@/components/quality-badges";
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
      composerIssues: sumByCheckType(modules, "composer_completeness"),
      deprecated: sumByCheckType(modules, "deprecated_annotation"),
      secrets: sumByCheckType(modules, "hardcoded_secret"),
      securityAdvisories: sumByCheckType(modules, "security_advisory"),
      abandoned: sumByCheckType(modules, "abandoned_dependency"),
      outdated: sumByCheckType(modules, "outdated_dependency"),
      phpstanErrors: sumByCheckType(modules, "phpstan_error"),
      phpmdIssues: sumByCheckType(modules, "phpmd_issue"),
      phpcsViolations: sumByCheckType(modules, "phpcs_violation"),
      phpCompatIssues: sumByCheckType(modules, "php_compat_issue"),
      phpmetricsIssues: sumByCheckType(modules, "phpmetrics_issue"),
      magentoUpgradeBlockers:
        sumByCheckType(modules, "magento_php_incompatible") + sumByCheckType(modules, "magento_version_blocker"),
      crossModuleConflicts:
        sumByCheckType(modules, "plugin_conflict") +
        sumByCheckType(modules, "composer_conflict") +
        sumByCheckType(modules, "webapi_route_conflict") +
        sumByCheckType(modules, "db_schema_conflict") +
        sumByCheckType(modules, "circular_dependency"),
      licenseRisks: sumByCheckType(modules, "license_risk"),
      phpunitFailures: sumByCheckType(modules, "phpunit_failure"),
    }),
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
            <StatTile
              label="Hardcoded secrets"
              value={totals.secrets}
              accent={totals.secrets > 0 ? palette.status.critical : undefined}
              description="API keys, passwords, or tokens written directly in the code instead of a secure config. Anyone with code access can read them — fix urgently."
              findingTypes={["hardcoded_secret"]}
            />
            <StatTile
              label="Known vulnerabilities"
              value={totals.securityAdvisories}
              accent={totals.securityAdvisories > 0 ? palette.status.critical : undefined}
              description="Third-party libraries with publicly disclosed security flaws (CVEs). Each one cites the advisory it matched."
              findingTypes={["security_advisory"]}
            />
            <StatTile
              label="Deprecated usages"
              value={totals.deprecated}
              accent={totals.deprecated > 0 ? palette.status.warning : undefined}
              description="Code calling something Magento has marked for removal in a future version — works today, but will need updating before the next major upgrade."
              findingTypes={["deprecated_annotation"]}
            />
            <StatTile
              label="Composer issues"
              value={totals.composerIssues}
              accent={totals.composerIssues > 0 ? palette.status.warning : undefined}
              description="Problems with a module's own packaging metadata (Composer is Magento's package manager) — e.g. missing license info or test coverage declared incorrectly."
              findingTypes={["composer_completeness"]}
            />
            <StatTile
              label="Abandoned dependencies"
              value={totals.abandoned}
              accent={totals.abandoned > 0 ? palette.status.warning : undefined}
              description="Third-party libraries the maintainer has officially stopped supporting — no more fixes or security patches will ever come, even for new vulnerabilities."
              findingTypes={["abandoned_dependency"]}
            />
            <StatTile
              label="Outdated dependencies"
              value={totals.outdated}
              description="Third-party libraries with a newer version available. Not urgent on its own, but worth tracking so upgrades don't pile up."
              findingTypes={["outdated_dependency"]}
            />
            <StatTile
              label="Magento upgrade blockers"
              value={totals.magentoUpgradeBlockers}
              accent={totals.magentoUpgradeBlockers > 0 ? palette.status.critical : undefined}
              description="Modules that would break outright on the latest Magento release (wrong PHP version or incompatible Magento package requirement) — these block an upgrade project until fixed."
              findingTypes={["magento_php_incompatible", "magento_version_blocker"]}
            />
            <StatTile
              label="PHP static-analysis findings"
              value={
                totals.phpstanErrors +
                totals.phpmdIssues +
                totals.phpcsViolations +
                totals.phpCompatIssues +
                totals.phpmetricsIssues
              }
              accent={
                totals.phpstanErrors +
                  totals.phpmdIssues +
                  totals.phpcsViolations +
                  totals.phpCompatIssues +
                  totals.phpmetricsIssues >
                0
                  ? palette.status.warning
                  : undefined
              }
              description="Code-quality issues caught by automated PHP analysis tools (bugs, style violations, overly complex code, risky metrics) — a proxy for how much technical debt a module carries."
              findingTypes={["phpstan_error", "phpmd_issue", "phpcs_violation", "php_compat_issue", "phpmetrics_issue"]}
            />
            <StatTile
              label="Cross-module conflicts"
              value={totals.crossModuleConflicts}
              accent={totals.crossModuleConflicts > 0 ? palette.status.warning : undefined}
              description="Two modules silently fighting over the same plugin hook, Composer package version, REST route, or database column — or a circular module.xml sequence that breaks setup:upgrade outright. Each shows up on every module involved."
              findingTypes={[
                "plugin_conflict",
                "composer_conflict",
                "webapi_route_conflict",
                "db_schema_conflict",
                "circular_dependency",
              ]}
            />
            <StatTile
              label="License risks"
              value={totals.licenseRisks}
              accent={totals.licenseRisks > 0 ? palette.status.warning : undefined}
              description="Modules declaring a strong-copyleft license (GPL/AGPL/SSPL) — bundling one into a commercial store may carry real redistribution obligations worth reviewing."
              findingTypes={["license_risk"]}
            />
            <StatTile
              label="PHPUnit test failures"
              value={totals.phpunitFailures}
              accent={totals.phpunitFailures > 0 ? palette.status.warning : undefined}
              description="Failing tests from a module's own Test/Unit/ suite, actually executed via its own vendor/bin/phpunit — only for modules that ship a standalone-runnable phpunit setup."
              findingTypes={["phpunit_failure"]}
            />
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
