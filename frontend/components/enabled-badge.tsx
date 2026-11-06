import { Badge } from "@/components/ui/badge";

export function EnabledBadge({ enabled }: { enabled: boolean | null }) {
  if (enabled === null) return <Badge variant="outline">unknown</Badge>;
  return enabled ? (
    <Badge variant="default">enabled</Badge>
  ) : (
    <Badge variant="secondary">disabled</Badge>
  );
}
