export const instant = false;

import type { Metadata } from "next";
import GraphClient from "./GraphClient";

// See app/modules/[id]/page.tsx's identical constant for why this needs its
// own server-only env var rather than every other page's browser-facing
// apiUrl() default.
const SERVER_SIDE_API_URL = process.env.API_INTERNAL_URL ?? "http://api:8000";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  try {
    const res = await fetch(`${SERVER_SIDE_API_URL}/modules/${id}`, { cache: "no-store" });
    if (res.ok) {
      // Only `name` is actually used here (a tab title), so a minimal local
      // type beats pulling in the full generated ModuleDetail response shape.
      const moduleData = (await res.json()) as { name: string };
      return { title: `${moduleData.name} — Graph` };
    }
  } catch {
    // Falls through to the generic title below — a tab title is never worth
    // failing the page over.
  }
  return { title: `Module ${id} — Graph` };
}

export default async function DependencyGraphPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <GraphClient id={id} />;
}
