"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { EnabledBadge } from "@/components/enabled-badge";
import { StateBadge } from "@/components/state-badge";
import { TagBadge } from "@/components/tag-badge";
import { QualityBadges } from "@/components/quality-badges";
import { TooltipProvider } from "@/components/ui/tooltip";
import { apiFetch } from "@/lib/api";
import { notifyQueryParamChange, useQueryParam } from "@/lib/use-query-param";
import type { components } from "@/lib/api-types";

type ModuleDetail = components["schemas"]["ModuleDetail"];
type ModuleSummary = components["schemas"]["ModuleSummary"];

// Same fetchModule/fetchModules shape ModuleDetailClient.tsx already
// defines, duplicated rather than extracted into a shared lib — two tiny
// one-line wrappers, not worth a new shared module for (CLAUDE.md: three
// similar lines beat a premature abstraction). The queryKeys below
// deliberately match ModuleDetailClient's own ("module", id) / ("modules")
// exactly, so arriving here from a module page (or the Similar modules
// card) that already fetched the same data is an instant cache hit.
async function fetchModule(id: string): Promise<ModuleDetail> {
  return apiFetch(`/modules/${id}`);
}

async function fetchModules(): Promise<ModuleSummary[]> {
  return apiFetch("/modules");
}

function dependenciesList(module: ModuleDetail, idByName: Map<string, number>) {
  if (module.dependencies.length === 0) {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <div className="flex flex-wrap items-center gap-x-1">
      {module.dependencies.map((dep, i) => {
        const depId = idByName.get(dep);
        return (
          <span key={dep}>
            {depId !== undefined ? (
              <Link href={`/modules/${depId}`} className="text-primary hover:underline">
                {dep}
              </Link>
            ) : (
              <span className="text-muted-foreground">{dep}</span>
            )}
            {i < module.dependencies.length - 1 ? "," : ""}
          </span>
        );
      })}
    </div>
  );
}

// Tags/findings/dependencies are all structured, parser-derived data, so
// they compare cleanly side by side. "Integrations" (per CLAUDE.md's Phase
// 21 framing) has no structured field yet -- it only exists today as free
// text inside the AI-written README's own "## Integrations" section, which
// this page doesn't attempt to scrape out and re-render a second time;
// "View full module →" links to each module's own detail page for that.
function ModuleColumn({ module, allModules }: { module: ModuleDetail; allModules: ModuleSummary[] | undefined }) {
  const idByName = useMemo(() => {
    const map = new Map<string, number>();
    for (const m of allModules ?? []) {
      if (m.repo_root === module.repo_root) map.set(m.name, m.id);
    }
    return map;
  }, [allModules, module.repo_root]);

  return (
    <div className="rounded-2xl bg-card p-5 shadow-sm flex flex-col gap-4 flex-1 min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="text-xl font-semibold tracking-tight truncate">{module.name}</h2>
        <Link href={`/modules/${module.id}`} className="text-sm text-primary hover:underline whitespace-nowrap">
          View full module →
        </Link>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <EnabledBadge enabled={module.enabled} />
        <StateBadge state={module.state} />
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-muted-foreground pt-1.5">Composer</dt>
        <dd className="pt-1.5">{module.composer_name ?? "—"}</dd>
      </dl>

      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Tags</span>
        {module.tags.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            {module.tags.map((tag) => (
              <TagBadge key={tag} tag={tag} />
            ))}
          </div>
        ) : (
          <span className="text-sm text-muted-foreground">—</span>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Quality findings</span>
        <QualityBadges findingCounts={module.finding_counts} />
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Depends on</span>
        {dependenciesList(module, idByName)}
      </div>
    </div>
  );
}

function ModulePicker({ label, value, onPick, options }: {
  label: string;
  value: string | null;
  onPick: (id: string) => void;
  options: ModuleSummary[];
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <select
        value={value ?? ""}
        onChange={(e) => onPick(e.target.value)}
        className="h-9 rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30"
      >
        <option value="" disabled>
          Choose a module…
        </option>
        {options.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function CompareClient() {
  const a = useQueryParam("a");
  const b = useQueryParam("b");

  const modulesQuery = useQuery({ queryKey: ["modules"], queryFn: fetchModules });
  const aQuery = useQuery({ queryKey: ["module", a], queryFn: () => fetchModule(a!), enabled: a !== null });
  const bQuery = useQuery({ queryKey: ["module", b], queryFn: () => fetchModule(b!), enabled: b !== null });

  function pick(param: "a" | "b", id: string) {
    const params = new URLSearchParams(window.location.search);
    params.set(param, id);
    window.history.pushState(null, "", `/modules/compare?${params.toString()}`);
    notifyQueryParamChange();
  }

  return (
    <TooltipProvider>
      <div className="flex flex-col gap-6 p-6 max-w-6xl mx-auto">
        <h1 className="text-2xl font-semibold tracking-tight">Compare modules</h1>

        {(!a || !b) && modulesQuery.data && (
          <div className="rounded-2xl bg-card p-5 shadow-sm flex flex-wrap gap-4">
            <ModulePicker label="Module A" value={a} onPick={(id) => pick("a", id)} options={modulesQuery.data} />
            <ModulePicker label="Module B" value={b} onPick={(id) => pick("b", id)} options={modulesQuery.data} />
          </div>
        )}

        {a && b && (
          <div className="flex flex-col md:flex-row gap-4 items-start">
            {aQuery.data && <ModuleColumn module={aQuery.data} allModules={modulesQuery.data} />}
            {aQuery.isLoading && <p>Loading...</p>}
            {aQuery.isError && <p className="text-destructive">Failed to load module {a}.</p>}

            {bQuery.data && <ModuleColumn module={bQuery.data} allModules={modulesQuery.data} />}
            {bQuery.isLoading && <p>Loading...</p>}
            {bQuery.isError && <p className="text-destructive">Failed to load module {b}.</p>}
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}
