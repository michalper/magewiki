"use client";

import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { FindingsPreviewList } from "@/components/findings-preview-list";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";
import { useDocumentTitle } from "@/lib/use-document-title";
import { useQueryParam } from "@/lib/use-query-param";

type UpgradeImpactResponse = components["schemas"]["UpgradeImpactResponse"];

async function fetchUpgradeImpact(repoRoot: string, version: string): Promise<UpgradeImpactResponse> {
  return apiFetch(
    `/repos/upgrade-impact?repo_root=${encodeURIComponent(repoRoot)}&version=${encodeURIComponent(version)}`,
  );
}

export default function UpgradeImpactClient() {
  useDocumentTitle("Upgrade impact");
  const repoRoot = useQueryParam("repo_root");
  const [versionInput, setVersionInput] = useState("");
  // Submitting is its own piece of state (not just "the input's current
  // value") so the query only ever runs for a version the user actually
  // asked to check -- typing doesn't refetch on every keystroke.
  const [submittedVersion, setSubmittedVersion] = useState<string | null>(null);

  const impactQuery = useQuery({
    queryKey: ["upgrade-impact", repoRoot, submittedVersion],
    queryFn: () => {
      /* v8 ignore next */
      if (repoRoot === null || submittedVersion === null) throw new Error("unreachable: query disabled");
      return fetchUpgradeImpact(repoRoot, submittedVersion);
    },
    enabled: repoRoot !== null && submittedVersion !== null,
  });

  function handleSubmit(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmed = versionInput.trim();
    if (trimmed) setSubmittedVersion(trimmed);
  }

  return (
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-3xl mx-auto w-full">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Upgrade impact</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Pick a Magento release and see which already-scanned modules in this repo would break —
          reads the last scan&apos;s data, does not scan this repo again.
        </p>
      </div>

      {repoRoot === null ? (
        <p className="text-muted-foreground">
          No repo selected. Pick one from the{" "}
          <Link href="/repos" className="text-primary hover:underline">
            Repos
          </Link>{" "}
          page.
        </p>
      ) : (
        <>
          <p className="truncate font-mono text-sm text-muted-foreground" title={repoRoot}>
            {repoRoot}
          </p>

          <form onSubmit={handleSubmit} className="flex items-end gap-2">
            <div className="flex-1">
              <label htmlFor="upgrade-impact-version" className="text-sm text-muted-foreground">
                Target Magento version
              </label>
              <Input
                id="upgrade-impact-version"
                value={versionInput}
                onChange={(e) => setVersionInput(e.target.value)}
                placeholder="e.g. 2.4.7"
              />
            </div>
            <Button type="submit" disabled={versionInput.trim() === ""}>
              Check
            </Button>
          </form>

          {impactQuery.isLoading && <p>Checking...</p>}
          {impactQuery.isError && (
            <p className="text-destructive">
              {impactQuery.error instanceof Error
                ? impactQuery.error.message
                : "Failed to check upgrade impact."}
            </p>
          )}

          {impactQuery.data && (
            <div className="flex flex-col gap-4">
              <p className="text-sm">
                {impactQuery.data.blocked_modules.length} of {impactQuery.data.checked_count} module
                {impactQuery.data.checked_count === 1 ? "" : "s"} would break on{" "}
                {impactQuery.data.version}.
              </p>

              {impactQuery.data.blocked_modules.length === 0 ? (
                <p className="text-muted-foreground">No blocking findings.</p>
              ) : (
                impactQuery.data.blocked_modules.map((module) => (
                  <div key={module.module_id} className="rounded-2xl bg-card p-5 shadow-sm">
                    <Link href={`/modules/${module.module_id}`} className="font-medium hover:underline">
                      {module.name}
                    </Link>
                    <div className="mt-2">
                      <FindingsPreviewList
                        findings={module.findings}
                        limit={module.findings.length}
                        footer={null}
                      />
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
