import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function TagBadge({ tag }: { tag: string }) {
  return (
    <Tooltip>
      <TooltipTrigger className="inline-flex">
        <Badge variant="outline">{tag}</Badge>
      </TooltipTrigger>
      <TooltipContent>Tag: assigned from MageWiki&apos;s controlled tag vocabulary.</TooltipContent>
    </Tooltip>
  );
}
