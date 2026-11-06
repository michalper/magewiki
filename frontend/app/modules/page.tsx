"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { EnabledBadge } from "@/components/enabled-badge";
import { SeverityBadge, SEVERITY_ORDER, type Severity } from "@/components/severity-badge";
import { notifyQueryParamChange, useQueryParam } from "@/lib/use-query-param";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { components, paths } from "@/lib/api-types";

type ModuleSummary =
  paths["/modules"]["get"]["responses"][200]["content"]["application/json"][number];
type ModuleDetail = components["schemas"]["ModuleDetail"];
type ScanResponse =
  paths["/scan"]["post"]["responses"][200]["content"]["application/json"];
type SortKey = "name" | "class_count" | "plugin_count" | "observer_count" | "last_scanned_at";

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetchModules(): Promise<ModuleSummary[]> {
  const res = await fetch(`${apiUrl()}/modules`);
  if (!res.ok) throw new Error(`API responded with ${res.status}`);
  return res.json();
}

async function fetchModuleDetail(id: number): Promise<ModuleDetail> {
  const res = await fetch(`${apiUrl()}/modules/${id}`);
  if (!res.ok) throw new Error(`API responded with ${res.status}`);
  return res.json();
}

async function triggerScan(path: string): Promise<ScanResponse> {
  const res = await fetch(`${apiUrl()}/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `API responded with ${res.status}`);
  }
  return res.json();
}

const STATE_VARIANTS: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  up_to_date: "default",
  pending: "outline",
  scanning: "outline",
  analyzing: "secondary",
  embedding: "secondary",
  failed: "destructive",
  paused_budget: "destructive",
};

function StateBadge({ state }: { state: string }) {
  return <Badge variant={STATE_VARIANTS[state] ?? "outline"}>{state}</Badge>;
}

function PresenceBadge({ present, label }: { present: boolean; label: string }) {
  return present ? (
    <SeverityBadge severity="ok">{label}</SeverityBadge>
  ) : (
    <SeverityBadge severity="none">no {label.toLowerCase()}</SeverityBadge>
  );
}

function QualityBadges({ module }: { module: ModuleSummary }) {
  const hasAny =
    module.composer_issue_count > 0 ||
    module.deprecated_count > 0 ||
    module.secrets_count > 0 ||
    module.security_advisory_count > 0 ||
    module.abandoned_dependency_count > 0 ||
    module.outdated_dependency_count > 0 ||
    module.phpstan_error_count > 0 ||
    module.phpmd_issue_count > 0 ||
    module.phpcs_violation_count > 0 ||
    module.php_compat_issue_count > 0 ||
    module.magento_php_incompatible_count > 0 ||
    module.magento_version_blocker_count > 0;
  if (!hasAny) return <SeverityBadge severity="ok">clean</SeverityBadge>;
  return (
    <div className="flex flex-wrap gap-1">
      {module.secrets_count > 0 && (
        <SeverityBadge severity="blocking">
          {module.secrets_count} secret{module.secrets_count === 1 ? "" : "s"}
        </SeverityBadge>
      )}
      {module.security_advisory_count > 0 && (
        <SeverityBadge severity="blocking">{module.security_advisory_count} CVE</SeverityBadge>
      )}
      {module.composer_issue_count > 0 && (
        <SeverityBadge severity="warning">{module.composer_issue_count} composer</SeverityBadge>
      )}
      {module.deprecated_count > 0 && (
        <SeverityBadge severity="warning">{module.deprecated_count} deprecated</SeverityBadge>
      )}
      {module.abandoned_dependency_count > 0 && (
        <SeverityBadge severity="warning">{module.abandoned_dependency_count} abandoned</SeverityBadge>
      )}
      {module.outdated_dependency_count > 0 && (
        <SeverityBadge severity="info">{module.outdated_dependency_count} outdated</SeverityBadge>
      )}
      {module.phpstan_error_count > 0 && (
        <SeverityBadge severity="warning">{module.phpstan_error_count} phpstan</SeverityBadge>
      )}
      {module.phpmd_issue_count > 0 && (
        <SeverityBadge severity="warning">{module.phpmd_issue_count} phpmd</SeverityBadge>
      )}
      {module.phpcs_violation_count > 0 && (
        <SeverityBadge severity="warning">{module.phpcs_violation_count} phpcs</SeverityBadge>
      )}
      {module.php_compat_issue_count > 0 && (
        <SeverityBadge severity="warning">{module.php_compat_issue_count} php-compat</SeverityBadge>
      )}
      {module.magento_php_incompatible_count > 0 && (
        <SeverityBadge severity="blocking">
          {module.magento_php_incompatible_count} magento-php
        </SeverityBadge>
      )}
      {module.magento_version_blocker_count > 0 && (
        <SeverityBadge severity="blocking">
          {module.magento_version_blocker_count} magento-upgrade
        </SeverityBadge>
      )}
    </div>
  );
}

function toCsv(modules: ModuleSummary[]): string {
  const headers = [
    "name",
    "composer_name",
    "source_type",
    "enabled",
    "state",
    "class_count",
    "plugin_count",
    "observer_count",
    "has_readme",
    "has_tests",
    "composer_issue_count",
    "deprecated_count",
    "secrets_count",
    "security_advisory_count",
    "abandoned_dependency_count",
    "outdated_dependency_count",
    "phpstan_error_count",
    "phpmd_issue_count",
    "phpcs_violation_count",
    "php_compat_issue_count",
    "magento_php_incompatible_count",
    "magento_version_blocker_count",
    "last_scanned_at",
  ];
  const escape = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = modules.map((m) =>
    [
      m.name,
      m.composer_name,
      m.source_type,
      m.enabled,
      m.state,
      m.class_count,
      m.plugin_count,
      m.observer_count,
      m.has_readme,
      m.has_tests,
      m.composer_issue_count,
      m.deprecated_count,
      m.secrets_count,
      m.security_advisory_count,
      m.abandoned_dependency_count,
      m.outdated_dependency_count,
      m.phpstan_error_count,
      m.phpmd_issue_count,
      m.phpcs_violation_count,
      m.php_compat_issue_count,
      m.magento_php_incompatible_count,
      m.magento_version_blocker_count,
      m.last_scanned_at,
    ]
      .map(escape)
      .join(",")
  );
  return [headers.join(","), ...rows].join("\n");
}

function downloadCsv(modules: ModuleSummary[]) {
  const csv = toCsv(modules);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `modules-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

const TABLE_COLUMN_COUNT = 13;
const PREVIEW_FINDING_COUNT = 5;

function ModuleRow({
  module,
  expanded,
  onToggle,
}: {
  module: ModuleSummary;
  expanded: boolean;
  onToggle: () => void;
}) {
  const detailQuery = useQuery({
    queryKey: ["module", module.id],
    queryFn: () => fetchModuleDetail(module.id),
    enabled: expanded,
  });

  return (
    <>
      <TableRow>
        <TableCell>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={expanded}
              aria-label={expanded ? "Collapse" : "Expand"}
              className="text-muted-foreground hover:text-foreground"
            >
              {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            </button>
            <Link href={`/modules/${module.id}`} className="font-medium hover:text-primary hover:underline">
              {module.name}
            </Link>
          </div>
        </TableCell>
        <TableCell className="text-muted-foreground">{module.composer_name ?? "—"}</TableCell>
        <TableCell>
          <EnabledBadge enabled={module.enabled} />
        </TableCell>
        <TableCell>
          <StateBadge state={module.state} />
        </TableCell>
        <TableCell>{module.source_type}</TableCell>
        <TableCell>
          <PresenceBadge present={module.has_readme} label="README" />
        </TableCell>
        <TableCell>
          <PresenceBadge present={module.has_tests} label="Tests" />
        </TableCell>
        <TableCell>
          <QualityBadges module={module} />
        </TableCell>
        <TableCell>
          {module.tags.length === 0 ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            <div className="flex flex-wrap gap-1">
              {module.tags.map((tag) => (
                <Badge key={tag} variant="outline">
                  {tag}
                </Badge>
              ))}
            </div>
          )}
        </TableCell>
        <TableCell className="text-right">{module.class_count}</TableCell>
        <TableCell className="text-right">{module.plugin_count}</TableCell>
        <TableCell className="text-right">{module.observer_count}</TableCell>
        <TableCell className="text-muted-foreground">
          {new Date(module.last_scanned_at).toLocaleString()}
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell colSpan={TABLE_COLUMN_COUNT} className="bg-muted/30 whitespace-normal">
            {module.has_module_doc && (
              <Link
                href={`/modules/${module.id}#readme`}
                className="inline-flex items-center gap-1 text-sm text-primary hover:underline pt-2"
              >
                View AI-generated README →
              </Link>
            )}
            {detailQuery.isLoading && <p className="text-sm text-muted-foreground py-2">Loading findings...</p>}
            {detailQuery.isError && <p className="text-sm text-destructive py-2">Failed to load findings.</p>}
            {detailQuery.data &&
              (detailQuery.data.quality_findings.length === 0 ? (
                <p className="text-sm text-muted-foreground py-2">No quality findings.</p>
              ) : (
                <div className="py-2 space-y-2">
                  <ul className="text-sm space-y-1.5">
                    {[...detailQuery.data.quality_findings]
                      .sort((a, b) => SEVERITY_ORDER[a.severity as Severity] - SEVERITY_ORDER[b.severity as Severity])
                      .slice(0, PREVIEW_FINDING_COUNT)
                      .map((f, i) => (
                        <li key={i} className="flex items-center gap-2 overflow-x-auto">
                          <SeverityBadge severity={f.severity as Severity}>{f.severity}</SeverityBadge>
                          <span className="font-mono text-muted-foreground shrink-0 whitespace-nowrap">
                            {f.file_path}
                            {f.line ? `:${f.line}` : ""}
                          </span>
                          <span className="whitespace-nowrap">{f.message}</span>
                        </li>
                      ))}
                  </ul>
                  {detailQuery.data.quality_findings.length > PREVIEW_FINDING_COUNT && (
                    <Link href={`/modules/${module.id}`} className="text-sm text-primary hover:underline">
                      View all {detailQuery.data.quality_findings.length} findings →
                    </Link>
                  )}
                </div>
              ))}
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

function SortableHead({
  label,
  sortKeyValue,
  currentKey,
  currentDir,
  onToggle,
  className,
}: {
  label: string;
  sortKeyValue: SortKey;
  currentKey: SortKey;
  currentDir: "asc" | "desc";
  onToggle: (key: SortKey) => void;
  className?: string;
}) {
  return (
    <TableHead className={className}>
      <button
        type="button"
        className="inline-flex items-center gap-1"
        onClick={() => onToggle(sortKeyValue)}
      >
        {label}
        {currentKey === sortKeyValue && (currentDir === "asc" ? "↑" : "↓")}
      </button>
    </TableHead>
  );
}

export default function ModulesPage() {
  const [path, setPath] = useState("");
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [stateFilter, setStateFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  // Read directly from the URL — avoids useSearchParams' Suspense-boundary
  // requirement for a filter this page doesn't need to statically render.
  const repoFilter = useQueryParam("repo");
  const queryClient = useQueryClient();

  function clearRepoFilter() {
    window.history.replaceState(null, "", "/modules");
    notifyQueryParamChange();
  }

  const modulesQuery = useQuery({ queryKey: ["modules"], queryFn: fetchModules });

  const scanMutation = useMutation({
    mutationFn: triggerScan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["modules"] });
    },
  });

  const sources = useMemo(
    () => Array.from(new Set((modulesQuery.data ?? []).map((m) => m.source_type))).sort(),
    [modulesQuery.data]
  );
  const states = useMemo(
    () => Array.from(new Set((modulesQuery.data ?? []).map((m) => m.state))).sort(),
    [modulesQuery.data]
  );

  const filteredAndSorted = useMemo(() => {
    const list = (modulesQuery.data ?? []).filter((m) => {
      if (repoFilter && m.repo_root !== repoFilter) return false;
      if (sourceFilter !== "all" && m.source_type !== sourceFilter) return false;
      if (stateFilter !== "all" && m.state !== stateFilter) return false;
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        if (!m.name.toLowerCase().includes(q) && !(m.composer_name ?? "").toLowerCase().includes(q)) {
          return false;
        }
      }
      return true;
    });
    const dir = sortDir === "asc" ? 1 : -1;
    return [...list].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }, [modulesQuery.data, repoFilter, search, sourceFilter, stateFilter, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function toggleExpanded(id: number) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-7xl mx-auto w-full">
      <h1 className="text-2xl font-semibold tracking-tight">Modules</h1>

      {repoFilter && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Filtering by repo:</span>
          <span className="font-mono">{repoFilter}</span>
          <button type="button" onClick={clearRepoFilter} className="text-primary hover:underline">
            Clear
          </button>
        </div>
      )}

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (path.trim()) scanMutation.mutate(path.trim());
        }}
      >
        <Input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="/path/to/magento-store-or-module"
          className="font-mono"
        />
        <Button type="submit" disabled={scanMutation.isPending || !path.trim()}>
          {scanMutation.isPending ? "Scanning..." : "Scan"}
        </Button>
      </form>

      {scanMutation.isError && (
        <p className="text-destructive text-sm">{(scanMutation.error as Error).message}</p>
      )}

      {scanMutation.isSuccess && (
        <div className="text-sm text-muted-foreground space-y-1">
          <p>
            Found {scanMutation.data.modules_found} modules (
            {scanMutation.data.modules_created} created,{" "}
            {scanMutation.data.modules_updated} updated) in{" "}
            {scanMutation.data.duration_seconds.toFixed(2)}s.{" "}
            {scanMutation.data.tasks_enqueued} analysis tasks queued.
          </p>
          {scanMutation.data.warnings.map((w, i) => (
            <p key={i} className="text-orange-600 dark:text-orange-400">
              {w}
            </p>
          ))}
        </div>
      )}

      {modulesQuery.isLoading && <p>Loading modules...</p>}
      {modulesQuery.isError && <p className="text-destructive">Failed to load modules.</p>}

      {modulesQuery.data && modulesQuery.data.length === 0 && (
        <p className="text-muted-foreground">No modules scanned yet.</p>
      )}

      {modulesQuery.data && modulesQuery.data.length > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search name or composer name..."
              className="max-w-xs"
            />
            <select
              value={sourceFilter}
              onChange={(e) => setSourceFilter(e.target.value)}
              className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30"
            >
              <option value="all">All sources</option>
              {sources.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="h-8 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30"
            >
              <option value="all">All states</option>
              {states.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <Button type="button" variant="outline" size="sm" onClick={() => downloadCsv(filteredAndSorted)}>
              Export CSV
            </Button>
            <span className="text-sm text-muted-foreground ml-auto">
              {filteredAndSorted.length} of {modulesQuery.data.length} modules
            </span>
          </div>

          <div className="rounded-2xl bg-card p-2 shadow-sm">
          <Table>
            <TableHeader>
              <TableRow>
                <SortableHead
                  label="Name"
                  sortKeyValue="name"
                  currentKey={sortKey}
                  currentDir={sortDir}
                  onToggle={toggleSort}
                />
                <TableHead>Composer name</TableHead>
                <TableHead>Enabled</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>README</TableHead>
                <TableHead>Tests</TableHead>
                <TableHead>Quality</TableHead>
                <TableHead>Tags</TableHead>
                <SortableHead
                  label="Classes"
                  sortKeyValue="class_count"
                  currentKey={sortKey}
                  currentDir={sortDir}
                  onToggle={toggleSort}
                  className="text-right"
                />
                <SortableHead
                  label="Plugins"
                  sortKeyValue="plugin_count"
                  currentKey={sortKey}
                  currentDir={sortDir}
                  onToggle={toggleSort}
                  className="text-right"
                />
                <SortableHead
                  label="Observers"
                  sortKeyValue="observer_count"
                  currentKey={sortKey}
                  currentDir={sortDir}
                  onToggle={toggleSort}
                  className="text-right"
                />
                <SortableHead
                  label="Last scanned"
                  sortKeyValue="last_scanned_at"
                  currentKey={sortKey}
                  currentDir={sortDir}
                  onToggle={toggleSort}
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredAndSorted.map((m) => (
                <ModuleRow
                  key={m.id}
                  module={m}
                  expanded={expandedIds.has(m.id)}
                  onToggle={() => toggleExpanded(m.id)}
                />
              ))}
            </TableBody>
          </Table>
          </div>
        </>
      )}
    </div>
  );
}
