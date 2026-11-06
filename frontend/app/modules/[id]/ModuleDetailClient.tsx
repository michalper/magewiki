"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown, { type Components } from "react-markdown";
import { Badge } from "@/components/ui/badge";
import { EnabledBadge } from "@/components/enabled-badge";
import { SeverityBadge, SEVERITY_ORDER, type Severity } from "@/components/severity-badge";
import { StateBadge } from "@/components/state-badge";
import { apiFetch, apiUrl } from "@/lib/api";
import type { components } from "@/lib/api-types";

type ModuleDetail = components["schemas"]["ModuleDetail"];

const PREVIEW_FINDING_COUNT = 10;

// No Tailwind typography plugin in this project — style the rendered README
// Markdown directly instead of pulling in another dependency for it.
const README_MARKDOWN_COMPONENTS: Components = {
  h1: (props) => <h3 className="text-base font-semibold mt-4 mb-2 first:mt-0" {...props} />,
  h2: (props) => <h3 className="text-base font-semibold mt-4 mb-2 first:mt-0" {...props} />,
  h3: (props) => <h4 className="text-sm font-semibold mt-3 mb-1.5 first:mt-0" {...props} />,
  p: (props) => <p className="mb-3 last:mb-0 leading-relaxed" {...props} />,
  ul: (props) => <ul className="list-disc pl-5 mb-3 space-y-1" {...props} />,
  ol: (props) => <ol className="list-decimal pl-5 mb-3 space-y-1" {...props} />,
  a: (props) => <a className="text-primary hover:underline" {...props} />,
  code: (props) => <code className="bg-background/60 rounded px-1 py-0.5 font-mono text-xs" {...props} />,
  strong: (props) => <strong className="font-semibold" {...props} />,
};

async function fetchModule(id: string): Promise<ModuleDetail> {
  return apiFetch(`/modules/${id}`);
}

async function fetchReadme(id: string): Promise<string | null> {
  // apiFetch always parses JSON and can't special-case 404 as "not an error" —
  // this is the one fetch in the app that returns plain text and treats a
  // missing README as a valid, non-error result, so it stays bespoke.
  const res = await fetch(`${apiUrl()}/modules/${id}/readme`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API responded with ${res.status}`);
  return res.text();
}

export default function ModuleDetailClient({ id }: { id: string }) {
  const moduleQuery = useQuery({ queryKey: ["module", id], queryFn: () => fetchModule(id) });
  const readmeQuery = useQuery({ queryKey: ["module-readme", id], queryFn: () => fetchReadme(id) });

  return (
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-4xl mx-auto w-full">
      <Link href="/modules" className="text-sm text-primary hover:underline self-start">
        ← All modules
      </Link>

      {moduleQuery.isLoading && <p>Loading...</p>}
      {moduleQuery.isError && <p className="text-destructive">Failed to load module.</p>}

      {moduleQuery.data && (
        <>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{moduleQuery.data.name}</h1>
            <EnabledBadge enabled={moduleQuery.data.enabled} />
            <StateBadge state={moduleQuery.data.state} />
            {moduleQuery.data.tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
            <SeverityBadge severity={moduleQuery.data.has_readme ? "ok" : "none"}>
              {moduleQuery.data.has_readme ? "README" : "no README"}
            </SeverityBadge>
            <SeverityBadge severity={moduleQuery.data.has_tests ? "ok" : "none"}>
              {moduleQuery.data.has_tests ? "tests" : "no tests"}
            </SeverityBadge>
          </div>
          <Link href={`/modules/${id}/graph`} className="text-sm text-primary hover:underline self-start">
            View dependency graph →
          </Link>
          <p className="text-sm text-muted-foreground">
            Last scanned {new Date(moduleQuery.data.last_scanned_at).toLocaleString()} — composer:{" "}
            {moduleQuery.data.composer_name ?? "—"}
          </p>

          {moduleQuery.data.dependencies.length > 0 && (
            <div className="text-sm">
              <span className="font-medium">Depends on: </span>
              {moduleQuery.data.dependencies.join(", ")}
            </div>
          )}

          <div id="readme" className="rounded-2xl bg-card p-5 shadow-sm scroll-mt-20">
            <h2 className="text-lg font-medium mb-3">README</h2>
            {readmeQuery.isLoading && <p className="text-sm text-muted-foreground">Loading...</p>}
            {readmeQuery.data === null && (
              <p className="text-sm text-muted-foreground">This module has not been analyzed yet.</p>
            )}
            {readmeQuery.data && (
              <div className="text-sm bg-muted rounded-xl p-4 overflow-x-auto">
                <ReactMarkdown components={README_MARKDOWN_COMPONENTS}>{readmeQuery.data}</ReactMarkdown>
              </div>
            )}
          </div>

          {moduleQuery.data.quality_findings.length > 0 && (
            <div className="rounded-2xl bg-card p-5 shadow-sm">
              <h2 className="text-lg font-medium mb-3">
                Quality findings{" "}
                <span className="text-sm font-normal text-muted-foreground">
                  (most severe {Math.min(PREVIEW_FINDING_COUNT, moduleQuery.data.quality_findings.length)} of{" "}
                  {moduleQuery.data.quality_findings.length})
                </span>
              </h2>
              <ul className="text-sm space-y-2">
                {[...moduleQuery.data.quality_findings]
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
                {moduleQuery.data.quality_findings.length > PREVIEW_FINDING_COUNT && (
                  <li className="text-muted-foreground">
                    +{moduleQuery.data.quality_findings.length - PREVIEW_FINDING_COUNT} more — use Export CSV
                    on the modules list for the full set
                  </li>
                )}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
