"use client";

import { useEffect } from "react";

// Client component pages can't export Next.js's `metadata`/title template
// (that's a Server Component-only API), so every such page previously shared
// the root layout's bare "MageWiki-AI" tab title. Mirrors that layout's own
// "%s · MageWiki-AI" template manually.
export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = `${title} · MageWiki-AI`;
  }, [title]);
}
