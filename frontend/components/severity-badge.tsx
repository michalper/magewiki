import { Badge } from "@/components/ui/badge";

export type Severity = "blocking" | "warning" | "info" | "ok" | "none";

export const SEVERITY_ORDER: Record<Severity, number> = { blocking: 0, warning: 1, info: 2, ok: 3, none: 4 };

const SEVERITY_CLASSES: Record<Severity, string> = {
  blocking:
    "border-transparent bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400",
  warning:
    "border-transparent bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-400",
  info: "border-transparent bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-400",
  ok: "border-transparent bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400",
  none: "border-transparent bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
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
