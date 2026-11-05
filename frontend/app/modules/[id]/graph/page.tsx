export const instant = false;

import GraphClient from "./GraphClient";

export default async function DependencyGraphPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <GraphClient id={id} />;
}
