"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { SeverityBadge } from "@/components/severity-badge";
import type { paths } from "@/lib/api-types";

type RepoSummary = paths["/repos"]["get"]["responses"][200]["content"]["application/json"][number];

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetchRepos(): Promise<RepoSummary[]> {
  const res = await fetch(`${apiUrl()}/repos`);
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
  const reposQuery = useQuery({ queryKey: ["repos"], queryFn: fetchRepos });

  return (
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-5xl mx-auto w-full">
      <h1 className="text-2xl font-semibold tracking-tight">Repos</h1>

      {reposQuery.isLoading && <p>Loading...</p>}
      {reposQuery.isError && <p className="text-red-600">Failed to load repos.</p>}

      {reposQuery.data && reposQuery.data.length === 0 && (
        <p className="text-zinc-500">No repos scanned yet.</p>
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
                <span className="text-sm text-zinc-500">
                  {repo.module_count} module{repo.module_count === 1 ? "" : "s"}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-sm text-zinc-500">
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
    </div>
  );
}
