"use client";

import Link from "next/link";
import type { MouseEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { QualityBadges } from "@/components/quality-badges";
import { SeverityBadge } from "@/components/severity-badge";
import { Button } from "@/components/ui/button";
import { apiFetch, apiUrl } from "@/lib/api";
import type { paths } from "@/lib/api-types";
import { useDocumentTitle } from "@/lib/use-document-title";

function downloadSbom(e: MouseEvent, repoRoot: string) {
  e.preventDefault();
  e.stopPropagation();
  window.open(`${apiUrl()}/repos/sbom?repo_root=${encodeURIComponent(repoRoot)}`, "_self");
}

type RepoSummary = paths["/repos"]["get"]["responses"][200]["content"]["application/json"][number];
type ModuleOverlapEntry =
  paths["/modules/overlap"]["get"]["responses"][200]["content"]["application/json"][number];
type DuplicateModulePairEntry =
  paths["/modules/duplicate-pairs"]["get"]["responses"][200]["content"]["application/json"][number];

async function fetchRepos(): Promise<RepoSummary[]> {
  return apiFetch("/repos");
}

async function fetchModuleOverlap(): Promise<ModuleOverlapEntry[]> {
  return apiFetch("/modules/overlap");
}

async function fetchDuplicatePairs(): Promise<DuplicateModulePairEntry[]> {
  return apiFetch("/modules/duplicate-pairs");
}

export default function ReposPage() {
  useDocumentTitle("Repos");
  const reposQuery = useQuery({ queryKey: ["repos"], queryFn: fetchRepos });
  const overlapQuery = useQuery({ queryKey: ["modules-overlap"], queryFn: fetchModuleOverlap });
  const duplicatesQuery = useQuery({ queryKey: ["modules-duplicate-pairs"], queryFn: fetchDuplicatePairs });

  return (
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-5xl mx-auto w-full" suppressHydrationWarning>
      {/* suppressHydrationWarning above: see app/modules/page.tsx's own
          top-level div for the full explanation -- the onboarding wizard's
          first-visit dialog marks this div inert via a direct DOM write
          Next's hydration-diff otherwise flags as a false mismatch. */}
      <h1 className="text-2xl font-semibold tracking-tight">Repos</h1>

      {reposQuery.isLoading && <p>Loading...</p>}
      {reposQuery.isError && <p className="text-destructive">Failed to load repos.</p>}

      {reposQuery.data && reposQuery.data.length === 0 && (
        <p className="text-muted-foreground">No repos scanned yet.</p>
      )}

      {reposQuery.data && reposQuery.data.length > 0 && (
        <div className="flex flex-col gap-3">
          {reposQuery.data.map((repo) => (
            <Link
              key={repo.repo_root}
              href={`/modules?repo=${encodeURIComponent(repo.repo_root)}`}
              className="flex flex-col gap-2 rounded-2xl bg-card p-5 shadow-sm transition-colors hover:bg-accent/40"
            >
              <div className="flex items-center justify-between gap-2">
                {/* min-w-0: a flex child's default min-width is its content's
                    natural width, so without this a long repo path just
                    pushed the module-count span off the right edge of the
                    screen instead of truncating -- confirmed on a real
                    380px phone width. shrink-0 on the count keeps it from
                    being squeezed in turn once the path can truncate. */}
                <span className="min-w-0 truncate font-mono text-sm" title={repo.repo_root}>
                  {repo.repo_root}
                </span>
                <span className="shrink-0 whitespace-nowrap text-sm text-muted-foreground">
                  {repo.module_count} module{repo.module_count === 1 ? "" : "s"}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
                <span>
                  {repo.enabled_count}/{repo.module_count} enabled
                </span>
                <span>
                  {repo.has_readme_count}/{repo.module_count} with README
                </span>
                <span>
                  {repo.has_tests_count}/{repo.module_count} with tests
                </span>
                <span>Last scanned {new Date(repo.last_scanned_at).toLocaleString()}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <QualityBadges findingCounts={repo.finding_counts} />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={(e) => downloadSbom(e, repo.repo_root)}
                >
                  Download SBOM
                </Button>
              </div>
            </Link>
          ))}
        </div>
      )}

      {overlapQuery.isLoading && <p>Loading...</p>}
      {overlapQuery.isError && <p className="text-destructive">Failed to load module overlap.</p>}

      {overlapQuery.data && overlapQuery.data.length > 0 && (
        <div className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold tracking-tight">Shared across stores</h2>
          <p className="text-sm text-muted-foreground">
            Modules found under more than one repo — a shared in-house module, or the same
            third-party module repeated across the fleet.
          </p>
          <div className="rounded-2xl bg-card p-2 shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="p-3 font-medium">Module</th>
                  <th className="p-3 font-medium">Stores</th>
                  <th className="p-3 font-medium">Version</th>
                  <th className="p-3 font-medium">In</th>
                </tr>
              </thead>
              <tbody>
                {overlapQuery.data.map((entry) => (
                  <tr key={entry.name} className="border-t border-border">
                    <td className="p-3 font-mono">{entry.name}</td>
                    <td className="p-3">{entry.store_count}</td>
                    <td className="p-3">
                      {entry.version_drift ? (
                        <SeverityBadge severity="warning">drift</SeverityBadge>
                      ) : (
                        <SeverityBadge severity="ok">same</SeverityBadge>
                      )}
                    </td>
                    <td className="p-3">
                      <div className="flex flex-wrap gap-x-3 gap-y-1">
                        {entry.stores.map((store) => (
                          <span key={store.repo_root} className="flex items-baseline gap-1">
                            <Link
                              href={`/modules?repo=${encodeURIComponent(store.repo_root)}`}
                              className="font-mono text-xs text-muted-foreground hover:text-foreground hover:underline"
                            >
                              {store.repo_root}
                            </Link>
                            <span className="font-mono text-xs text-muted-foreground/70">
                              ({store.setup_version ?? "unknown"})
                            </span>
                          </span>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {duplicatesQuery.isLoading && <p>Loading...</p>}
      {duplicatesQuery.isError && <p className="text-destructive">Failed to load duplicate modules.</p>}

      {duplicatesQuery.data && duplicatesQuery.data.length > 0 && (
        <div className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold tracking-tight">Possible duplicate modules</h2>
          <p className="text-sm text-muted-foreground">
            Different modules (not the same vendor/package) whose AI-generated summaries are
            semantically very close — likely doing the same third-party integration twice.
          </p>
          <div className="rounded-2xl bg-card p-2 shadow-sm">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="p-3 font-medium">Module A</th>
                  <th className="p-3 font-medium">Module B</th>
                  <th className="p-3 font-medium">Similarity</th>
                  <th className="p-3 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {duplicatesQuery.data.map((pair) => (
                  <tr
                    key={`${pair.module_a_id}-${pair.module_b_id}`}
                    className="border-t border-border"
                  >
                    <td className="p-3 font-mono">{pair.module_a_name}</td>
                    <td className="p-3 font-mono">{pair.module_b_name}</td>
                    <td className="p-3">{Math.round(pair.similarity * 100)}%</td>
                    <td className="p-3">
                      <Link
                        href={`/modules/compare?a=${pair.module_a_id}&b=${pair.module_b_id}`}
                        className="text-primary hover:underline"
                      >
                        Compare
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
