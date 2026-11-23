import { BadgeTooltip } from "@/components/badge-tooltip";
import { Badge } from "@/components/ui/badge";

export function TagBadge({ tag }: { tag: string }) {
  return (
    <BadgeTooltip tooltip="Tag: assigned from MageWiki's controlled tag vocabulary.">
      <Badge variant="outline">{tag}</Badge>
    </BadgeTooltip>
  );
}
