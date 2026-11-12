"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

type SimilarModuleEntry = components["schemas"]["SimilarModuleEntry"];

async function fetchSimilarModules(id: string): Promise<SimilarModuleEntry[]> {
  return apiFetch(`/modules/${id}/similar`);
}

// Phase 21: semantic duplicate/overlap detection, reusing Phase 4's existing
// module-level embeddings (no new scan, no new embedding call -- see
// app/search/similar_modules.py). The empty state covers two genuinely
// different real situations identically ("this module hasn't been
// analyzed/embedded yet" and "no other module is similar enough") -- the
// backend endpoint itself doesn't distinguish them (both legitimately mean
// "nothing to show"), so the UI doesn't pretend to either.
export function SimilarModulesCard({ moduleId }: { moduleId: string }) {
  const similarQuery = useQuery({
    queryKey: ["module-similar", moduleId],
    queryFn: () => fetchSimilarModules(moduleId),
  });

  return (
    <div className="rounded-2xl bg-card p-5 shadow-sm flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Similar modules</h2>
      {similarQuery.isLoading && <p className="text-sm text-muted-foreground">Loading...</p>}
      {similarQuery.isError && <p className="text-sm text-destructive">Failed to load similar modules.</p>}
      {similarQuery.data && similarQuery.data.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Not enough analyzed modules yet to compare — this needs an AI-generated module summary
          (and an embedding key configured) for both modules.
        </p>
      )}
      {similarQuery.data && similarQuery.data.length > 0 && (
        <ul className="flex flex-col gap-1.5">
          {similarQuery.data.map((entry) => (
            <li key={entry.module_id} className="flex items-center justify-between gap-3 text-sm">
              <Link
                href={`/modules/compare?a=${moduleId}&b=${entry.module_id}`}
                className="text-primary hover:underline truncate"
              >
                {entry.name}
              </Link>
              <span className="text-muted-foreground whitespace-nowrap">
                {Math.round(entry.similarity * 100)}% similar
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
