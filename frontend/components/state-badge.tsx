import { BadgeTooltip } from "@/components/badge-tooltip";
import { BADGE_COLOR_CLASSES } from "@/components/severity-badge";
import { Badge } from "@/components/ui/badge";

// Each of the 7 module states gets its own color — collapsing them into a
// handful of shared badge variants made e.g. "analyzing" and "embedding"
// (two different in-progress steps) indistinguishable at a glance on pages
// whose core purpose is state visibility.
const STATE_CLASSES: Record<string, string> = {
  up_to_date: BADGE_COLOR_CLASSES.green,
  pending: BADGE_COLOR_CLASSES.muted,
  scanning: BADGE_COLOR_CLASSES.blue,
  analyzing: BADGE_COLOR_CLASSES.indigo,
  embedding: BADGE_COLOR_CLASSES.purple,
  failed: BADGE_COLOR_CLASSES.red,
  paused_budget: BADGE_COLOR_CLASSES.orange,
};

const STATE_DESCRIPTIONS: Record<string, string> = {
  up_to_date: "Scan state: fully analyzed, embedded, and up to date with the current source.",
  pending: "Scan state: discovered, waiting for analysis to start.",
  scanning: "Scan state: files are currently being hashed and diffed.",
  analyzing: "Scan state: the AI is currently summarizing changed files and synthesizing the module doc.",
  embedding: "Scan state: generating search embeddings for the synthesized doc.",
  failed: "Scan state: analysis failed — see the module's last_error for details.",
  paused_budget: "Scan state: paused because the monthly LLM budget was exceeded.",
};

export function StateBadge({ state }: { state: string }) {
  return (
    <BadgeTooltip tooltip={STATE_DESCRIPTIONS[state] ?? `Scan state: ${state}.`}>
      <Badge variant="outline" className={STATE_CLASSES[state]}>
        State: {state}
      </Badge>
    </BadgeTooltip>
  );
}
