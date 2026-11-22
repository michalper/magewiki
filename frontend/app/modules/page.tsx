"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import { streamSse } from "@/lib/sse";
import { downloadCsv, toCsv } from "@/lib/csv";
import { AccessTokenPrompt } from "@/components/access-token-gate";
import { AccessTokenRequiredError } from "@/lib/access-token";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EnabledBadge } from "@/components/enabled-badge";
import { CHECK_TYPES, QualityBadges } from "@/components/quality-badges";
import { SeverityBadge, SEVERITY_ORDER, type Severity } from "@/components/severity-badge";
import { StateBadge } from "@/components/state-badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { TagBadge } from "@/components/tag-badge";
import { FindingMessage } from "@/components/finding-message";
import { apiFetch, apiUrl } from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { useDocumentTitle } from "@/lib/use-document-title";
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

type ModuleListResponse = paths["/modules"]["get"]["responses"][200]["content"]["application/json"];
type ModuleSummary = ModuleListResponse["modules"][number];
type ModuleDetail = components["schemas"]["ModuleDetail"];
type ScanResponse =
  paths["/scan"]["post"]["responses"][200]["content"]["application/json"];
type ScanRootsResponse = components["schemas"]["ScanRootsResponse"];
type ScanStreamEvent =
  | { event: "discovered"; total: number }
  | { event: "store"; name: string; index: number; total: number }
  | { event: "module"; name: string; status: string; index: number; total: number; warning: string | null }
  | { event: "done"; result: ScanResponse }
  | { event: "error"; detail: string };
type SortKey = "name" | "class_count" | "plugin_count" | "observer_count" | "last_scanned_at";

// source_type and state are both small, fixed enumerations the backend's own
// module state machine and scanner discovery logic define (see CLAUDE.md) --
// listed here directly rather than derived from whatever happens to be
// present in the current (now server-filtered) page of data, so every
// filterable value is always offered, not just the ones the active filters
// happen to still show.
const SOURCE_TYPES = ["app_code", "vendor", "standalone", "composer_path"];
const MODULE_STATES = ["pending", "scanning", "analyzing", "embedding", "up_to_date", "failed", "paused_budget"];

type ModulesQueryParams = {
  search?: string;
  sourceType?: string;
  state?: string;
  enabled?: "true" | "false" | "unknown";
  repoRoot?: string;
  finding?: string;
  hasDoc?: boolean;
  sortBy: SortKey;
  sortDir: "asc" | "desc";
  prioritizeDoc: boolean;
  limit: number;
  offset: number;
};

function buildModulesQuery(params: ModulesQueryParams): string {
  const qs = new URLSearchParams();
  if (params.search) qs.set("search", params.search);
  if (params.sourceType) qs.set("source_type", params.sourceType);
  if (params.state) qs.set("state", params.state);
  if (params.enabled) qs.set("enabled", params.enabled);
  if (params.repoRoot) qs.set("repo_root", params.repoRoot);
  if (params.finding) qs.set("finding", params.finding);
  if (params.hasDoc !== undefined) qs.set("has_doc", String(params.hasDoc));
  qs.set("sort_by", params.sortBy);
  qs.set("sort_dir", params.sortDir);
  if (params.prioritizeDoc) qs.set("prioritize_doc", "true");
  qs.set("limit", String(params.limit));
  qs.set("offset", String(params.offset));
  return qs.toString();
}

async function fetchModules(params: ModulesQueryParams): Promise<ModuleListResponse> {
  return apiFetch(`/modules?${buildModulesQuery(params)}`);
}

async function fetchModuleDetail(id: number): Promise<ModuleDetail> {
  return apiFetch(`/modules/${id}`);
}

async function fetchScanRoots(): Promise<ScanRootsResponse> {
  return apiFetch("/scan-roots");
}

async function streamScan(
  path: string,
  onEvent: (event: ScanStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await streamSse<ScanStreamEvent>(`${apiUrl()}/scan/stream`, { path }, onEvent, signal);
}

// A plain <select>'s own dropdown arrow is drawn by the browser/OS, not by
// us -- `padding-right` doesn't reliably push it away from the box edge (a
// real, reported-as-"looks broken" case: Chrome on macOS still renders the
// arrow flush against the border regardless of padding). appearance-none
// hides that native arrow entirely and a real lucide icon, absolutely
// positioned and vertically centered, replaces it with one we fully control.
function FilterSelect({
  value,
  onChange,
  ariaLabel,
  children,
}: {
  value: string | number;
  onChange: (value: string) => void;
  ariaLabel: string;
  children: React.ReactNode;
}) {
  return (
    <div className="relative inline-block">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={ariaLabel}
        className="h-8 appearance-none rounded-lg border border-input bg-transparent pl-2 pr-7 text-sm dark:bg-input/30"
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}

function PresenceBadge({ present, label }: { present: boolean; label: string }) {
  return (
    <Tooltip>
      <TooltipTrigger className="inline-flex">
        {present ? (
          <SeverityBadge severity="ok">{label}</SeverityBadge>
        ) : (
          <SeverityBadge severity="none">no {label.toLowerCase()}</SeverityBadge>
        )}
      </TooltipTrigger>
      <TooltipContent>
        {present
          ? `Has a ${label === "README" ? "README.md" : "Test/ directory"} in the module's own source.`
          : `No ${label === "README" ? "README.md" : "test files"} found in the module's own source.`}
      </TooltipContent>
    </Tooltip>
  );
}


function downloadModulesCsv(modules: ModuleSummary[]) {
  const headers = [
    "name",
    "composer_name",
    "setup_version",
    "source_type",
    "enabled",
    "state",
    "class_count",
    "plugin_count",
    "observer_count",
    "has_readme",
    "has_tests",
    ...CHECK_TYPES.map((c) => c.key),
    "last_scanned_at",
  ];
  const rows = modules.map((m) => [
    m.name,
    m.composer_name,
    m.setup_version,
    m.source_type,
    m.enabled,
    m.state,
    m.class_count,
    m.plugin_count,
    m.observer_count,
    m.has_readme,
    m.has_tests,
    ...CHECK_TYPES.map((c) => m.finding_counts[c.key] ?? 0),
    m.last_scanned_at,
  ]);
  downloadCsv(`modules-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(headers, rows));
}

const TABLE_COLUMN_COUNT = 14;
const PREVIEW_FINDING_COUNT = 5;
const PAGE_SIZE_OPTIONS = [5, 25, 50, 100, 200];
const DEFAULT_PAGE_SIZE = 25;
// How long the search box waits after the last keystroke before it re-filters
// the (potentially large, e.g. a 760-module fleet) list — re-filtering and
// re-rendering the whole table on every single keystroke is what made typing
// into this box visibly laggy before.
const SEARCH_DEBOUNCE_MS = 250;

// Mobile equivalent of a table row — a horizontally-scrolling 14-column table
// is unusable on a phone, so narrow screens get a stacked card instead (see
// the md:hidden / hidden md:block split at the call site). Links straight to
// the full detail page rather than reusing ModuleRow's inline expand, since a
// second copy of that findings-preview JSX isn't worth it for a mobile-only
// view — tapping through to the real page is a perfectly normal mobile
// pattern.
function ModuleCard({ module }: { module: ModuleSummary }) {
  return (
    <Link
      href={`/modules/${module.id}`}
      className="flex flex-col gap-2 rounded-2xl bg-card p-4 shadow-sm hover:bg-accent/40"
    >
      <div className="flex items-start justify-between gap-2">
        {/* min-w-0: a flex child's default min-width is its content's natural
            width, so without this the long module name just pushed the
            StateBadge off the right edge of the screen instead of truncating
            -- confirmed on a real 380px phone width. */}
        <span className="min-w-0 truncate font-medium" title={module.name}>
          {module.name}
        </span>
        <StateBadge state={module.state} />
      </div>
      <div className="text-xs text-muted-foreground">
        {module.composer_name ?? "—"}
        {module.setup_version ? ` · v${module.setup_version}` : ""}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <EnabledBadge enabled={module.enabled} />
        <PresenceBadge present={module.has_readme} label="README" />
        <PresenceBadge present={module.has_tests} label="Tests" />
      </div>
      <QualityBadges findingCounts={module.finding_counts} />
      {module.tags.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          <span className="text-xs text-muted-foreground">Tags:</span>
          {module.tags.map((tag) => (
            <TagBadge key={tag} tag={tag} />
          ))}
        </div>
      )}
      <div className="flex items-center justify-between border-t border-border/50 pt-2 text-xs text-muted-foreground">
        <span>
          {module.class_count} classes · {module.plugin_count} plugins · {module.observer_count} observers
        </span>
      </div>
      <div className="text-xs text-muted-foreground">
        {module.source_type} · scanned {new Date(module.last_scanned_at).toLocaleDateString()}
      </div>
    </Link>
  );
}

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
          <div className="flex min-w-0 items-center gap-1">
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={expanded}
              aria-label={expanded ? "Collapse" : "Expand"}
              className="shrink-0 text-muted-foreground hover:text-foreground"
            >
              {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            </button>
            <Link
              href={`/modules/${module.id}`}
              title={module.name}
              className="min-w-0 truncate font-medium hover:text-primary hover:underline"
            >
              {module.name}
            </Link>
          </div>
        </TableCell>
        <TableCell className="truncate text-muted-foreground" title={module.composer_name ?? undefined}>
          {module.composer_name ?? "—"}
        </TableCell>
        <TableCell className="truncate text-muted-foreground font-mono text-xs">{module.setup_version ?? "—"}</TableCell>
        <TableCell>
          <EnabledBadge enabled={module.enabled} />
        </TableCell>
        <TableCell>
          <StateBadge state={module.state} />
        </TableCell>
        <TableCell className="truncate">{module.source_type}</TableCell>
        <TableCell>
          <PresenceBadge present={module.has_readme} label="README" />
        </TableCell>
        <TableCell>
          <PresenceBadge present={module.has_tests} label="Tests" />
        </TableCell>
        <TableCell className="whitespace-normal">
          <QualityBadges findingCounts={module.finding_counts} />
        </TableCell>
        <TableCell className="whitespace-normal">
          {module.tags.length === 0 ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            <div className="flex flex-wrap gap-1">
              {module.tags.map((tag) => (
                <TagBadge key={tag} tag={tag} />
              ))}
            </div>
          )}
        </TableCell>
        <TableCell className="text-right">{module.class_count}</TableCell>
        <TableCell className="text-right">{module.plugin_count}</TableCell>
        <TableCell className="text-right">{module.observer_count}</TableCell>
        <TableCell className="truncate text-muted-foreground">
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
                        <li key={i} className="space-y-0.5">
                          <div className="flex items-center gap-2">
                            <SeverityBadge severity={f.severity as Severity}>{f.severity}</SeverityBadge>
                            <span className="font-mono text-muted-foreground whitespace-nowrap">
                              {f.file_path}
                              {f.line ? `:${f.line}` : ""}
                            </span>
                          </div>
                          <div><FindingMessage message={f.message} /></div>
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

function Pagination({
  page,
  pageCount,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
}: {
  page: number;
  pageCount: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}) {
  const rangeStart = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const rangeEnd = Math.min(total, page * pageSize);

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <span className="text-muted-foreground">
        {total === 0 ? "No modules" : `${rangeStart}–${rangeEnd} of ${total}`}
      </span>
      <div className="flex items-center gap-2">
        <FilterSelect value={pageSize} onChange={(v) => onPageSizeChange(Number(v))} ariaLabel="Modules per page">
          {PAGE_SIZE_OPTIONS.map((size) => (
            <option key={size} value={size}>
              {size} / page
            </option>
          ))}
        </FilterSelect>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
        >
          Previous
        </Button>
        <span className="text-muted-foreground">
          Page {page} of {pageCount}
        </span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pageCount}
        >
          Next
        </Button>
      </div>
    </div>
  );
}

function clearQueryParam(name: string) {
  const params = new URLSearchParams(window.location.search);
  params.delete(name);
  const query = params.toString();
  window.history.replaceState(null, "", query ? `/modules?${query}` : "/modules");
  notifyQueryParamChange();
}

export default function ModulesPage() {
  useDocumentTitle("Modules");
  const [path, setPath] = useState("");
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [stateFilter, setStateFilter] = useState("all");
  const [enabledFilter, setEnabledFilter] = useState("all");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  // Until the user explicitly picks a column to sort by, modules with a
  // real AI-generated doc float to the top regardless of sortKey -- on a
  // fleet that's only partially analyzed (true of any fleet with budget-
  // capped incremental analysis, not just a demo), the plain-alphabetical
  // default otherwise shows "not analyzed yet" for most rows by sheer
  // chance. An explicit sort-by-name click still means literal
  // alphabetical, with no doc-first grouping.
  const [hasUserSorted, setHasUserSorted] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const debouncedSearch = useDebouncedValue(search, SEARCH_DEBOUNCE_MS);
  // Read directly from the URL — avoids useSearchParams' Suspense-boundary
  // requirement for a filter this page doesn't need to statically render.
  const repoFilter = useQueryParam("repo");
  // Comma-separated check_type keys (e.g. a Stats tile summing several
  // check types, such as "Magento upgrade blockers") — module matches if
  // its finding_counts has a non-zero count for any of them.
  const findingFilter = useQueryParam("finding");
  // "true" to show only modules with a real AI-generated doc -- e.g. a demo
  // link that wants to lead with fully-analyzed examples rather than
  // whatever a fleet's current analysis coverage happens to be.
  const hasDocFilter = useQueryParam("has_doc");
  const queryClient = useQueryClient();

  const modulesQueryParams: ModulesQueryParams = {
    search: debouncedSearch.trim() || undefined,
    sourceType: sourceFilter !== "all" ? sourceFilter : undefined,
    state: stateFilter !== "all" ? stateFilter : undefined,
    enabled: enabledFilter !== "all" ? (enabledFilter as "true" | "false" | "unknown") : undefined,
    repoRoot: repoFilter || undefined,
    finding: findingFilter || undefined,
    hasDoc: hasDocFilter === "true" ? true : undefined,
    sortBy: sortKey,
    sortDir,
    prioritizeDoc: !hasUserSorted,
    limit: pageSize,
    offset: (page - 1) * pageSize,
  };
  const modulesQuery = useQuery({
    queryKey: ["modules", modulesQueryParams],
    queryFn: () => fetchModules(modulesQueryParams),
    // Every filter/sort/page change is a genuinely new queryKey (server-side
    // now does the filtering), which TanStack Query otherwise treats as a
    // brand-new query -- isLoading (and so the whole "Loading modules..."
    // branch below, which replaces the entire filter/table UI) would flip
    // true on every single keystroke/click instead of just the first load.
    // keepPreviousData keeps the last page's rows on screen (isFetching
    // still goes true) while the new one loads in the background.
    placeholderData: keepPreviousData,
  });
  // The fleet's total module count with NO filters applied -- distinct from
  // modulesQuery's own (filtered) total, used only to tell "nothing scanned
  // yet" apart from "filters matched nothing" and to render "X of Y" below.
  // limit: 1 -- only `total` is read from this one, never `modules`.
  const fleetCountQuery = useQuery({
    queryKey: ["modules", "fleet-count"],
    queryFn: () =>
      fetchModules({ sortBy: "name", sortDir: "asc", prioritizeDoc: false, limit: 1, offset: 0 }),
  });
  const scanRootsQuery = useQuery({ queryKey: ["scan-roots"], queryFn: fetchScanRoots });

  const [scanStatus, setScanStatus] = useState<"idle" | "running" | "done" | "error">("idle");
  const [scanLog, setScanLog] = useState<string[]>([]);
  const [scanProgress, setScanProgress] = useState<{ index: number; total: number } | null>(null);
  const [scanResult, setScanResult] = useState<ScanResponse | null>(null);
  const [scanError, setScanError] = useState<string | null>(null);
  const [scanNeedsToken, setScanNeedsToken] = useState(false);
  const scanLogRef = useRef<HTMLDivElement>(null);
  const scanAbortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    scanLogRef.current?.scrollTo({ top: scanLogRef.current.scrollHeight });
  }, [scanLog]);

  useEffect(() => {
    // Navigating away mid-scan must not leave the backend's scan (and the
    // whole-scan advisory lock it holds for its duration) running after the
    // page that was listening for its progress is gone.
    return () => scanAbortControllerRef.current?.abort();
  }, []);

  async function startScan() {
    // No guard here against a blank path or an already-running scan -- the
    // submit button is `disabled` in exactly those two conditions, and this
    // is its only caller.
    const trimmed = path.trim();

    setScanStatus("running");
    setScanLog([]);
    setScanProgress(null);
    setScanResult(null);
    setScanError(null);
    setScanNeedsToken(false);

    const controller = new AbortController();
    scanAbortControllerRef.current = controller;

    let eventsSinceRefresh = 0;
    try {
      await streamScan(trimmed, (event) => {
        if (event.event === "discovered") {
          setScanProgress({ index: 0, total: event.total });
          setScanLog((log) => [...log, `Found ${event.total} modules, scanning...`]);
        } else if (event.event === "store") {
          // A directory containing several stores side by side scans each
          // one in turn — reset the progress bar per store and mark the
          // boundary in the log, so it's clear which store is active.
          setScanProgress(null);
          setScanLog((log) => [...log, `=== Store ${event.index}/${event.total}: ${event.name} ===`]);
        } else if (event.event === "module") {
          const icon = event.status === "error" ? "✗" : "✓";
          const detail = event.warning ? `: ${event.warning}` : ` (${event.status})`;
          setScanProgress({ index: event.index, total: event.total });
          setScanLog((log) => [...log, `${icon} ${event.name}${detail}`]);
          // Refetching on every single module would mean hundreds of refetches
          // for a large store — throttle to every 5th module, plus always on
          // "done" below, so the table still fills in live without hammering
          // the API.
          eventsSinceRefresh += 1;
          if (eventsSinceRefresh >= 5) {
            eventsSinceRefresh = 0;
            queryClient.invalidateQueries({ queryKey: ["modules"] });
            // Also refresh any already-expanded row's detail panel — otherwise
            // it keeps showing the pre-scan doc/state while the list above it
            // has already moved on.
            queryClient.invalidateQueries({ queryKey: ["module"] });
          }
        } else if (event.event === "done") {
          setScanStatus("done");
          setScanResult(event.result);
          queryClient.invalidateQueries({ queryKey: ["modules"] });
          queryClient.invalidateQueries({ queryKey: ["module"] });
        } else {
          // Defensive: ScanStreamEvent's own type is exhaustively discovered |
          // store | module | done | error, so this "else" can only ever hold
          // "error" in practice.
          /* v8 ignore next */
          if (event.event === "error") {
            setScanStatus("error");
            setScanError(event.detail);
          }
        }
      }, controller.signal);
    } catch (err) {
      // An intentional abort (navigating away) isn't a failure worth showing —
      // the controls it would update may not even be mounted anymore.
      if ((err as Error).name === "AbortError") {
        // no-op
      } else if (err instanceof AccessTokenRequiredError) {
        setScanStatus("idle");
        setScanNeedsToken(true);
      } else {
        setScanStatus("error");
        setScanError((err as Error).message);
      }
    }
  }

  const modules = modulesQuery.data?.modules ?? [];
  const total = modulesQuery.data?.total ?? 0;
  const fleetTotal = fleetCountQuery.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / pageSize));

  // Each filter/search input resets the page to 1 directly in its own change
  // handler below (a plain event-handler setState, not this). This clamp is
  // the backstop for the cases that don't go through a handler
  // (repoFilter/findingFilter come from the URL via useQueryParam, and the
  // result set can also just shrink on refetch): never leave `page`
  // requesting data past the last real page. A conditional setState call
  // directly in the render body -- not inside an effect -- is React's own
  // documented pattern for "adjust state in response to a condition
  // changing while rendering" (https://react.dev/learn/you-might-not-need-an-effect);
  // it self-terminates the moment `page` no longer exceeds `pageCount`.
  if (modulesQuery.data && page > pageCount) {
    setPage(pageCount);
  }

  async function exportCsv() {
    // The visible table is just one page -- export every module matching the
    // current filters, not only what's currently on screen. total is already
    // known from modulesQuery, so this is exactly one extra request.
    const all = await fetchModules({ ...modulesQueryParams, limit: Math.max(1, Math.min(total, 5000)), offset: 0 });
    downloadModulesCsv(all.modules);
  }

  function toggleSort(key: SortKey) {
    setHasUserSorted(true);
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
    <TooltipProvider>
    {/* suppressHydrationWarning: the onboarding wizard (components/
        onboarding-wizard.tsx) opens its dialog the moment it learns,
        client-only, that this is a first visit -- Base UI's Dialog then
        marks this page's own top-level content div inert (aria-hidden +
        data-base-ui-inert) via a direct DOM write outside React's own
        reconciler, which Next's hydration-diff still catches as a real
        mismatch. Confirmed directly in a browser that no amount of
        deferring the dialog's open state (render-time via
        useSyncExternalStore, a plain useEffect, even a setTimeout(0), or
        not mounting the Dialog component at all until a post-mount flag
        flips) stops it -- and that suppressHydrationWarning only silences
        the exact element it's applied to, not a shared ancestor like
        <body>, so it has to live on every page's own top-level div (see
        this same comment, abbreviated, on the other pages with this
        pattern: chat, settings, repos, stats, the module detail page, and
        the dependency graph page). */}
    <div className="flex flex-col flex-1 gap-6 p-8 w-full" suppressHydrationWarning>
      <h1 className="text-2xl font-semibold tracking-tight">Modules</h1>

      {repoFilter && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Filtering by repo:</span>
          <span className="font-mono">{repoFilter}</span>
          <button type="button" onClick={() => clearQueryParam("repo")} className="text-primary hover:underline">
            Clear
          </button>
        </div>
      )}

      {findingFilter && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Filtering by finding:</span>
          <span className="font-mono">{findingFilter}</span>
          <button type="button" onClick={() => clearQueryParam("finding")} className="text-primary hover:underline">
            Clear
          </button>
        </div>
      )}

      {hasDocFilter === "true" && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-muted-foreground">Showing only modules with an AI-generated doc.</span>
          <button type="button" onClick={() => clearQueryParam("has_doc")} className="text-primary hover:underline">
            Clear
          </button>
        </div>
      )}

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void startScan();
        }}
      >
        <Input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="/path/to/magento-store-or-module"
          aria-label="Path to scan"
          className="font-mono"
        />
        <Button type="submit" disabled={scanStatus === "running" || !path.trim()}>
          {scanStatus === "running"
            ? scanProgress
              ? `Scanning... (${scanProgress.index}/${scanProgress.total})`
              : "Scanning..."
            : "Scan"}
        </Button>
      </form>

      {scanNeedsToken && (
        <AccessTokenPrompt
          onUnlock={() => {
            setScanNeedsToken(false);
            void startScan();
          }}
        />
      )}

      {scanRootsQuery.data &&
        (scanRootsQuery.data.scan_roots.length > 0 ? (
          <p className="text-xs text-muted-foreground -mt-4">
            Scannable under: <span className="font-mono">{scanRootsQuery.data.scan_roots.join(", ")}</span>
          </p>
        ) : (
          <p className="text-xs text-muted-foreground -mt-4">
            No scan roots configured — set <span className="font-mono">MAGEWIKI_SCAN_ROOT_1</span> in{" "}
            <span className="font-mono">.env</span> and restart.
          </p>
        ))}

      {(scanStatus === "running" || scanStatus === "done") && scanProgress && (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all"
            style={{ width: `${Math.min(100, (scanProgress.index / scanProgress.total) * 100)}%` }}
          />
        </div>
      )}

      {scanLog.length > 0 && (
        <div
          ref={scanLogRef}
          className="h-48 overflow-y-auto rounded-2xl bg-card p-3 font-mono text-xs leading-relaxed shadow-sm"
        >
          {scanLog.map((line, i) => (
            <div
              key={i}
              className={line.startsWith("✗") ? "text-destructive" : "text-muted-foreground"}
            >
              {line}
            </div>
          ))}
        </div>
      )}

      {scanStatus === "error" && <p className="text-destructive text-sm">{scanError}</p>}

      {scanStatus === "done" && scanResult && (
        <div className="text-sm text-muted-foreground space-y-1">
          <p>
            {scanResult.stores_scanned > 1 && `Scanned ${scanResult.stores_scanned} stores. `}
            Found {scanResult.modules_found} modules ({scanResult.modules_created} created,{" "}
            {scanResult.modules_updated} updated) in {scanResult.duration_seconds.toFixed(2)}s.{" "}
            {scanResult.tasks_enqueued} analysis tasks queued.
          </p>
        </div>
      )}

      {modulesQuery.isLoading && <p>Loading modules...</p>}
      {modulesQuery.isError && <p className="text-destructive">Failed to load modules.</p>}

      {modulesQuery.data && fleetCountQuery.data && fleetTotal === 0 && (
        <p className="text-muted-foreground">No modules scanned yet.</p>
      )}

      {modulesQuery.data && fleetCountQuery.data && fleetTotal > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              placeholder="Search name or composer name..."
              aria-label="Search modules"
              className="max-w-xs"
            />
            <FilterSelect
              value={sourceFilter}
              onChange={(v) => {
                setSourceFilter(v);
                setPage(1);
              }}
              ariaLabel="Filter by source"
            >
              <option value="all">All sources</option>
              {SOURCE_TYPES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </FilterSelect>
            <FilterSelect
              value={stateFilter}
              onChange={(v) => {
                setStateFilter(v);
                setPage(1);
              }}
              ariaLabel="Filter by state"
            >
              <option value="all">All states</option>
              {MODULE_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </FilterSelect>
            <FilterSelect
              value={enabledFilter}
              onChange={(v) => {
                setEnabledFilter(v);
                setPage(1);
              }}
              ariaLabel="Filter by enabled status"
            >
              <option value="all">All enabled status</option>
              <option value="true">Enabled</option>
              <option value="false">Disabled</option>
              <option value="unknown">Unknown</option>
            </FilterSelect>
            <Button type="button" variant="outline" size="sm" onClick={() => void exportCsv()}>
              Export CSV
            </Button>
            <span className="text-sm text-muted-foreground ml-auto">
              {total} of {fleetTotal} modules
            </span>
          </div>

          <div className="flex flex-col gap-3 md:hidden">
            {modules.map((m) => (
              <ModuleCard key={m.id} module={m} />
            ))}
          </div>

          <div className="hidden rounded-2xl bg-card p-2 shadow-sm overflow-x-auto md:block">
          {/* table-fixed, with a fixed px width on every short/badge column (just
              enough for their worst-case label, e.g. "State: paused_budget" or
              "Enabled: unknown" — these never need more room no matter the monitor)
              and NO width at all on the free-text/badge-cluster columns (Composer
              name, Quality, Tags). table-layout:fixed hands those three whatever
              space is left over after the fixed columns, split evenly — so the
              table always fills the viewport, and the extra room on a wide monitor
              goes to the columns that can actually use it, not wasted as dead space
              or lost to a horizontal scrollbar.
              Name gets its own fixed floor (w-52) instead of sharing that leftover
              split: on a narrow window, splitting the remainder four ways crushed
              every module's name down to the same unreadable "Magento_…" (every
              real module in this project's own fleet shares that prefix, so a
              truncated name told you nothing about which module you were looking
              at — a user flagged exactly this on a small monitor). This column
              overflows into the container's own horizontal scroll rather than
              shrink further; the others still get `truncate` + a hover title as a
              fallback for an unusually long value. */}
          <Table className="w-auto min-w-full table-fixed">
            <TableHeader>
              <TableRow>
                <SortableHead
                  label="Name"
                  sortKeyValue="name"
                  currentKey={sortKey}
                  currentDir={sortDir}
                  onToggle={toggleSort}
                  className="w-52"
                />
                <TableHead className="min-w-32">Composer name</TableHead>
                <TableHead className="w-18">Version</TableHead>
                <TableHead className="w-30">Enabled</TableHead>
                <TableHead className="w-38">State</TableHead>
                <TableHead className="w-28">Source</TableHead>
                <TableHead className="w-19">README</TableHead>
                <TableHead className="w-16">Tests</TableHead>
                <TableHead className="min-w-40">Quality</TableHead>
                <TableHead className="min-w-32">Tags</TableHead>
                <SortableHead
                  label="Classes"
                  sortKeyValue="class_count"
                  currentKey={sortKey}
                  currentDir={sortDir}
                  onToggle={toggleSort}
                  className="w-17 text-right"
                />
                <SortableHead
                  label="Plugins"
                  sortKeyValue="plugin_count"
                  currentKey={sortKey}
                  currentDir={sortDir}
                  onToggle={toggleSort}
                  className="w-17 text-right"
                />
                <SortableHead
                  label="Observers"
                  sortKeyValue="observer_count"
                  currentKey={sortKey}
                  currentDir={sortDir}
                  onToggle={toggleSort}
                  className="w-19 text-right"
                />
                <SortableHead
                  label="Last scanned"
                  sortKeyValue="last_scanned_at"
                  currentKey={sortKey}
                  currentDir={sortDir}
                  onToggle={toggleSort}
                  className="w-36"
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {modules.map((m) => (
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

          <Pagination
            page={page}
            pageCount={pageCount}
            pageSize={pageSize}
            total={total}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        </>
      )}
    </div>
    </TooltipProvider>
  );
}
