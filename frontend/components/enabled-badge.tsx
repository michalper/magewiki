import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const DESCRIPTIONS: Record<"enabled" | "disabled" | "unknown", string> = {
  enabled: "Listed as enabled in this store's app/etc/config.php.",
  disabled: "Listed as disabled in this store's app/etc/config.php.",
  unknown: "Not listed in app/etc/config.php at all — present on disk but not registered in any store.",
};

const LABELS: Record<"enabled" | "disabled" | "unknown", string> = {
  enabled: "Enabled: yes",
  disabled: "Enabled: no",
  unknown: "Enabled: unknown",
};

export function EnabledBadge({ enabled }: { enabled: boolean | null }) {
  const key = enabled === null ? "unknown" : enabled ? "enabled" : "disabled";
  const variant = key === "unknown" ? "outline" : key === "enabled" ? "default" : "secondary";
  return (
    <Tooltip>
      <TooltipTrigger className="inline-flex">
        <Badge variant={variant}>{LABELS[key]}</Badge>
      </TooltipTrigger>
      <TooltipContent>{DESCRIPTIONS[key]}</TooltipContent>
    </Tooltip>
  );
}
