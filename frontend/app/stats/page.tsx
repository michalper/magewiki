"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useChartPalette } from "@/components/chart-palette";
import type { paths } from "@/lib/api-types";

type ModuleSummary =
  paths["/modules"]["get"]["responses"][200]["content"]["application/json"][number];

// Fixed order, never derived from the data being rendered — see CLAUDE.md's
// module state machine and the dataviz skill's "assign categorical hues in
// fixed order, never cycled" rule.
const STATE_ORDER = [
  "up_to_date",
  "pending",
  "scanning",
  "analyzing",
  "embedding",
  "paused_budget",
  "failed",
];

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetchModules(): Promise<ModuleSummary[]> {
  const res = await fetch(`${apiUrl()}/modules`);
  if (!res.ok) throw new Error(`API responded with ${res.status}`);
  return res.json();
}

function StatTile({
  label,
  value,
  accent,
}: {
  label: string;
  value: number | string;
  accent?: string;
}) {
  return (
    <div
      className="flex flex-col gap-1 rounded-2xl bg-card p-5 shadow-sm"
      style={accent ? { borderLeftColor: accent, borderLeftWidth: 3 } : undefined}
    >
      <span className="text-xs uppercase tracking-wide text-zinc-500">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
    </div>
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
      <span className="text-sm text-center text-zinc-500">{label}</span>
    </div>
  );
}

function StateDonut({ modules }: { modules: ModuleSummary[] }) {
  const palette = useChartPalette();
  const counts = STATE_ORDER.map((state) => ({
    name: state,
    value: modules.filter((m) => m.state === state).length,
    color: palette.categorical[STATE_ORDER.indexOf(state)],
  })).filter((d) => d.value > 0);

  if (counts.length === 0) return null;

  return (
    <div className="rounded-2xl bg-card p-5 shadow-sm">
      <h3 className="text-sm font-medium mb-2 text-zinc-500">Module state</h3>
      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie data={counts} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} stroke="none">
            {counts.map((entry) => (
              <Cell key={entry.name} fill={entry.color} />
            ))}
          </Pie>
          <Tooltip />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

function TopFindingsBar({ modules }: { modules: ModuleSummary[] }) {
  const palette = useChartPalette();
  const data = modules
    .map((m) => ({
      name: m.name,
      total:
        m.composer_issue_count +
        m.deprecated_count +
        m.secrets_count +
        m.security_advisory_count +
        m.abandoned_dependency_count +
        m.outdated_dependency_count +
        m.phpstan_error_count +
        m.phpmd_issue_count +
        m.phpcs_violation_count +
        m.php_compat_issue_count,
    }))
    .filter((d) => d.total > 0)
    .sort((a, b) => b.total - a.total)
    .slice(0, 10);

  if (data.length === 0) {
    return (
      <div className="rounded-2xl bg-card p-5 shadow-sm">
        <h3 className="text-sm font-medium mb-2 text-zinc-500">Top modules by quality findings</h3>
        <p className="text-sm text-zinc-500">No quality findings across any scanned module.</p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl bg-card p-5 shadow-sm">
      <h3 className="text-sm font-medium mb-2 text-zinc-500">Top modules by quality findings</h3>
      <ResponsiveContainer width="100%" height={Math.max(200, data.length * 32)}>
        <BarChart data={data} layout="vertical" margin={{ left: 24 }}>
          <CartesianGrid horizontal={false} stroke={palette.ink.gridline} />
          <XAxis type="number" allowDecimals={false} tick={{ fill: palette.ink.muted, fontSize: 12 }} />
          <YAxis type="category" dataKey="name" width={160} tick={{ fill: palette.ink.muted, fontSize: 12 }} />
          <Tooltip />
          <Bar dataKey="total" fill={palette.sequential} radius={[0, 4, 4, 0]} maxBarSize={24} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function StatsPage() {
  const modulesQuery = useQuery({ queryKey: ["modules"], queryFn: fetchModules });
  const palette = useChartPalette();
  const modules = useMemo(() => modulesQuery.data ?? [], [modulesQuery.data]);

  const totals = useMemo(
    () => ({
      total: modules.length,
      withReadme: modules.filter((m) => m.has_readme).length,
      withTests: modules.filter((m) => m.has_tests).length,
      composerIssues: modules.reduce((sum, m) => sum + m.composer_issue_count, 0),
      deprecated: modules.reduce((sum, m) => sum + m.deprecated_count, 0),
      secrets: modules.reduce((sum, m) => sum + m.secrets_count, 0),
      securityAdvisories: modules.reduce((sum, m) => sum + m.security_advisory_count, 0),
      abandoned: modules.reduce((sum, m) => sum + m.abandoned_dependency_count, 0),
      outdated: modules.reduce((sum, m) => sum + m.outdated_dependency_count, 0),
      phpstanErrors: modules.reduce((sum, m) => sum + m.phpstan_error_count, 0),
      phpmdIssues: modules.reduce((sum, m) => sum + m.phpmd_issue_count, 0),
      phpcsViolations: modules.reduce((sum, m) => sum + m.phpcs_violation_count, 0),
      phpCompatIssues: modules.reduce((sum, m) => sum + m.php_compat_issue_count, 0),
    }),
    [modules]
  );

  return (
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-5xl mx-auto w-full">
      <h1 className="text-2xl font-semibold tracking-tight">Stats</h1>

      {modulesQuery.isLoading && <p>Loading...</p>}
      {modulesQuery.isError && <p className="text-red-600">Failed to load modules.</p>}

      {modulesQuery.data && modules.length === 0 && (
        <p className="text-zinc-500">No modules scanned yet.</p>
      )}

      {modulesQuery.data && modules.length > 0 && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatTile label="Modules scanned" value={totals.total} />
            <StatTile
              label="Hardcoded secrets"
              value={totals.secrets}
              accent={totals.secrets > 0 ? palette.status.critical : undefined}
            />
            <StatTile
              label="Known vulnerabilities"
              value={totals.securityAdvisories}
              accent={totals.securityAdvisories > 0 ? palette.status.critical : undefined}
            />
            <StatTile
              label="Deprecated usages"
              value={totals.deprecated}
              accent={totals.deprecated > 0 ? palette.status.warning : undefined}
            />
            <StatTile
              label="Composer issues"
              value={totals.composerIssues}
              accent={totals.composerIssues > 0 ? palette.status.warning : undefined}
            />
            <StatTile
              label="Abandoned dependencies"
              value={totals.abandoned}
              accent={totals.abandoned > 0 ? palette.status.warning : undefined}
            />
            <StatTile label="Outdated dependencies" value={totals.outdated} />
            <StatTile
              label="PHP static-analysis findings"
              value={totals.phpstanErrors + totals.phpmdIssues + totals.phpcsViolations + totals.phpCompatIssues}
              accent={
                totals.phpstanErrors + totals.phpmdIssues + totals.phpcsViolations + totals.phpCompatIssues > 0
                  ? palette.status.warning
                  : undefined
              }
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
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <StateDonut modules={modules} />
            <TopFindingsBar modules={modules} />
          </div>
        </>
      )}
    </div>
  );
}
