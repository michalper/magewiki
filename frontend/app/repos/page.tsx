"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { SeverityBadge } from "@/components/severity-badge";
import type { paths } from "@/lib/api-types";
import { useDocumentTitle } from "@/lib/use-document-title";

type RepoSummary = paths["/repos"]["get"]["responses"][200]["content"]["application/json"][number];
type ModuleOverlapEntry =
  paths["/modules/overlap"]["get"]["responses"][200]["content"]["application/json"][number];

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetchRepos(): Promise<RepoSummary[]> {
  const res = await fetch(`${apiUrl()}/repos`);
  if (!res.ok) throw new Error(`API responded with ${res.status}`);
  return res.json();
}

async function fetchModuleOverlap(): Promise<ModuleOverlapEntry[]> {
  const res = await fetch(`${apiUrl()}/modules/overlap`);
  if (!res.ok) throw new Error(`API responded with ${res.status}`);
  return res.json();
}

function totalFindings(r: RepoSummary): number {
  return (
    r.composer_issue_count +
    r.deprecated_count +
    r.secrets_count +
    r.security_advisory_count +
    r.abandoned_dependency_count +
    r.outdated_dependency_count +
    r.phpstan_error_count +
    r.phpmd_issue_count +
    r.phpcs_violation_count +
    r.php_compat_issue_count +
    r.magento_php_incompatible_count +
    r.magento_version_blocker_count
  );
}

export default function ReposPage() {
  useDocumentTitle("Repos");
  const reposQuery = useQuery({ queryKey: ["repos"], queryFn: fetchRepos });
  const overlapQuery = useQuery({ queryKey: ["modules-overlap"], queryFn: fetchModuleOverlap });

  return (
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-5xl mx-auto w-full">
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
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm">{repo.repo_root}</span>
                <span className="text-sm text-muted-foreground">
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
              <div className="flex flex-wrap gap-1">
                {totalFindings(repo) === 0 ? (
                  <SeverityBadge severity="ok">clean</SeverityBadge>
                ) : (
                  <>
                    {repo.secrets_count > 0 && (
                      <SeverityBadge severity="blocking">{repo.secrets_count} secrets</SeverityBadge>
                    )}
                    {repo.security_advisory_count > 0 && (
                      <SeverityBadge severity="blocking">{repo.security_advisory_count} CVE</SeverityBadge>
                    )}
                    {repo.composer_issue_count > 0 && (
                      <SeverityBadge severity="warning">{repo.composer_issue_count} composer</SeverityBadge>
                    )}
                    {repo.deprecated_count > 0 && (
                      <SeverityBadge severity="warning">{repo.deprecated_count} deprecated</SeverityBadge>
                    )}
                    {repo.abandoned_dependency_count > 0 && (
                      <SeverityBadge severity="warning">
                        {repo.abandoned_dependency_count} abandoned
                      </SeverityBadge>
                    )}
                    {repo.outdated_dependency_count > 0 && (
                      <SeverityBadge severity="info">{repo.outdated_dependency_count} outdated</SeverityBadge>
                    )}
                    {repo.phpstan_error_count > 0 && (
                      <SeverityBadge severity="warning">{repo.phpstan_error_count} phpstan</SeverityBadge>
                    )}
                    {repo.phpmd_issue_count > 0 && (
                      <SeverityBadge severity="warning">{repo.phpmd_issue_count} phpmd</SeverityBadge>
                    )}
                    {repo.phpcs_violation_count > 0 && (
                      <SeverityBadge severity="warning">{repo.phpcs_violation_count} phpcs</SeverityBadge>
                    )}
                    {repo.php_compat_issue_count > 0 && (
                      <SeverityBadge severity="warning">
                        {repo.php_compat_issue_count} php-compat
                      </SeverityBadge>
                    )}
                    {repo.magento_php_incompatible_count > 0 && (
                      <SeverityBadge severity="blocking">
                        {repo.magento_php_incompatible_count} magento-php
                      </SeverityBadge>
                    )}
                    {repo.magento_version_blocker_count > 0 && (
                      <SeverityBadge severity="blocking">
                        {repo.magento_version_blocker_count} magento-upgrade
                      </SeverityBadge>
                    )}
                  </>
                )}
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
                      <div className="flex flex-wrap gap-2">
                        {entry.stores.map((store) => (
                          <Link
                            key={store.repo_root}
                            href={`/modules?repo=${encodeURIComponent(store.repo_root)}`}
                            className="font-mono text-xs text-muted-foreground hover:text-foreground hover:underline"
                          >
                            {store.repo_root}
                          </Link>
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
    </div>
  );
}
