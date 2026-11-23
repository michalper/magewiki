import { BadgeTooltip } from "@/components/badge-tooltip";
import { SeverityBadge } from "@/components/severity-badge";

// Shared by the modules list (table rows + mobile cards) and the module
// detail page, which each used to render their own, subtly differently
// worded version of "does this module have a README / tests" -- a `label`
// of "README" or "Tests" picks the right noun in both branches below.
export function PresenceBadge({ present, label }: { present: boolean; label: string }) {
  const noun = label === "README" ? "README.md" : "Test/ directory";
  const missingNoun = label === "README" ? "README.md" : "test files";
  return (
    <BadgeTooltip
      tooltip={
        present
          ? `Has a ${noun} in the module's own source.`
          : `No ${missingNoun} found in the module's own source.`
      }
    >
      {present ? (
        <SeverityBadge severity="ok">{label}</SeverityBadge>
      ) : (
        <SeverityBadge severity="none">no {label.toLowerCase()}</SeverityBadge>
      )}
    </BadgeTooltip>
  );
}
