import { Badge } from "@/components/ui/badge";

// Each of the 7 module states gets its own color — collapsing them into a
// handful of shared badge variants made e.g. "analyzing" and "embedding"
// (two different in-progress steps) indistinguishable at a glance on pages
// whose core purpose is state visibility.
const STATE_CLASSES: Record<string, string> = {
  up_to_date: "border-transparent bg-green-100 text-green-700 dark:bg-green-950 dark:text-green-400",
  pending: "border-transparent bg-muted text-muted-foreground",
  scanning: "border-transparent bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-400",
  analyzing: "border-transparent bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-400",
  embedding: "border-transparent bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-400",
  failed: "border-transparent bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400",
  paused_budget: "border-transparent bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-400",
};

export function StateBadge({ state }: { state: string }) {
  return (
    <Badge variant="outline" className={STATE_CLASSES[state]}>
      {state}
    </Badge>
  );
}
