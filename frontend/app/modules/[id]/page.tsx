export const instant = false;

import ModuleDetailClient from "./ModuleDetailClient";

export default async function ModuleDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ModuleDetailClient id={id} />;
}
