"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { SeverityBadge, type Severity } from "@/components/severity-badge";
import type { components } from "@/lib/api-types";

type ModuleDetail = components["schemas"]["ModuleDetail"];

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetchModule(id: string): Promise<ModuleDetail> {
  const res = await fetch(`${apiUrl()}/modules/${id}`);
  if (!res.ok) throw new Error(`API responded with ${res.status}`);
  return res.json();
}

async function fetchReadme(id: string): Promise<string | null> {
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
      <Link href="/modules" className="text-sm underline underline-offset-4 self-start">
        ← All modules
      </Link>

      {moduleQuery.isLoading && <p>Loading...</p>}
      {moduleQuery.isError && <p className="text-red-600">Failed to load module.</p>}

      {moduleQuery.data && (
        <>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight font-mono">{moduleQuery.data.name}</h1>
            <Badge variant={moduleQuery.data.enabled ? "default" : "secondary"}>
              {moduleQuery.data.enabled ? "enabled" : "disabled"}
            </Badge>
            <Badge variant={moduleQuery.data.state === "up_to_date" ? "default" : "outline"}>
              {moduleQuery.data.state}
            </Badge>
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
          <Link href={`/modules/${id}/graph`} className="text-sm underline underline-offset-4 self-start">
            View dependency graph →
          </Link>
          <p className="text-sm text-zinc-500">
            Last scanned {new Date(moduleQuery.data.last_scanned_at).toLocaleString()} — composer:{" "}
            {moduleQuery.data.composer_name ?? "—"}
          </p>

          {moduleQuery.data.dependencies.length > 0 && (
            <div className="text-sm">
              <span className="font-medium">Depends on: </span>
              {moduleQuery.data.dependencies.join(", ")}
            </div>
          )}

          {moduleQuery.data.quality_findings.length > 0 && (
            <div>
              <h2 className="text-lg font-medium mb-2">Quality findings</h2>
              <ul className="text-sm space-y-1">
                {moduleQuery.data.quality_findings.slice(0, 20).map((f, i) => (
                  <li key={i} className="flex items-center gap-2">
                    <SeverityBadge severity={f.severity as Severity}>{f.severity}</SeverityBadge>
                    <span className="font-mono text-zinc-500">
                      {f.file_path}
                      {f.line ? `:${f.line}` : ""}
                    </span>
                    <span>{f.message}</span>
                  </li>
                ))}
                {moduleQuery.data.quality_findings.length > 20 && (
                  <li className="text-zinc-500">
                    +{moduleQuery.data.quality_findings.length - 20} more
                  </li>
                )}
              </ul>
            </div>
          )}

          <div>
            <h2 className="text-lg font-medium mb-2">README</h2>
            {readmeQuery.isLoading && <p className="text-sm text-zinc-500">Loading...</p>}
            {readmeQuery.data === null && (
              <p className="text-sm text-zinc-500">This module has not been analyzed yet.</p>
            )}
            {readmeQuery.data && (
              <pre className="whitespace-pre-wrap text-sm bg-zinc-50 dark:bg-zinc-900 rounded-lg p-4 overflow-x-auto">
                {readmeQuery.data}
              </pre>
            )}
          </div>
        </>
      )}
    </div>
  );
}
