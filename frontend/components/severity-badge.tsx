import { Badge } from "@/components/ui/badge";

export type Severity = "blocking" | "warning" | "info" | "ok" | "none";

export const SEVERITY_ORDER: Record<Severity, number> = { blocking: 0, warning: 1, info: 2, ok: 3, none: 4 };

// Shared by every badge component that colors itself by a semantic key
// (SeverityBadge here, StateBadge separately) -- named by color, not by
// meaning, so each badge's own Record<itsOwnKey, string> can reference a
// color without re-typing its Tailwind classes.
export const BADGE_COLOR_CLASSES = {
  red: "border-transparent bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400",
  orange: "border-transparent bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-400",
  blue: "border-transparent bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-400",
  green: "border-transparent bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400",
  indigo: "border-transparent bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-400",
  purple: "border-transparent bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-400",
  muted: "border-transparent bg-muted text-muted-foreground",
} as const;

const SEVERITY_CLASSES: Record<Severity, string> = {
  blocking: BADGE_COLOR_CLASSES.red,
  warning: BADGE_COLOR_CLASSES.orange,
  info: BADGE_COLOR_CLASSES.blue,
  ok: BADGE_COLOR_CLASSES.green,
  none: BADGE_COLOR_CLASSES.muted,
};

export function SeverityBadge({
  severity,
  children,
}: {
  severity: Severity;
  children: React.ReactNode;
}) {
  return (
    <Badge variant="outline" className={SEVERITY_CLASSES[severity]}>
      {children}
    </Badge>
  );
}
