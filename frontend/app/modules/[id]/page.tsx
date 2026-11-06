export const instant = false;

import type { Metadata } from "next";
import ModuleDetailClient from "./ModuleDetailClient";

// This runs server-side inside the `web` container, where NEXT_PUBLIC_API_URL
// (deliberately browser-facing — the host's exposed port, used by every other
// page in this app, which all fetch from the browser instead) resolves to
// this same container, not the `api` one. API_INTERNAL_URL is server-only
// (no NEXT_PUBLIC_ prefix, so it's never bundled into client JS either) and
// defaults to the docker-compose service name, reachable only from inside
// the network.
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
      const moduleData = await res.json();
      return { title: moduleData.name };
    }
  } catch {
    // Falls through to the generic title below — a tab title is never worth
    // failing the page over.
  }
  return { title: `Module ${id}` };
}

export default async function ModuleDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ModuleDetailClient id={id} />;
}
