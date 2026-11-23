import type { ReactNode } from "react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/**
 * Wraps a badge in the Tooltip/TooltipTrigger/TooltipContent shape every
 * badge-with-a-tooltip component (TagBadge, EnabledBadge, StateBadge) needs
 * identically — only the badge itself and the tooltip text differ per use.
 */
export function BadgeTooltip({ tooltip, children }: { tooltip: ReactNode; children: ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger className="inline-flex">{children}</TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}
