import type { components } from "@/lib/api-types";
import { FALLBACK_CHECK_TYPES, KPI_TILES, prettifyCheckType, type AccentLevel } from "@/lib/kpi-tiles";

type ModuleSummary = components["schemas"]["ModuleSummary"];

const ACCENT_ORDER: AccentLevel[] = ["critical", "warning", "none"];
const ACCENT_HEADINGS: Record<AccentLevel, string> = { critical: "Critical", warning: "Warning", none: "Other" };

// Only ever called after the total === 0 early return below, so `total` is
// always positive here -- no div-by-zero guard needed.
function percent(count: number, total: number): string {
  return `${Math.round((count / total) * 100)}%`;
}

function sumByCheckType(modules: ModuleSummary[], checkType: string): number {
  return modules.reduce((sum, m) => sum + (m.finding_counts[checkType] ?? 0), 0);
}

function totalFindings(module: ModuleSummary): number {
  return Object.values(module.finding_counts).reduce((sum, n) => sum + n, 0);
}

/**
 * A plain-Markdown repo health summary, meant to be pasted into a Slack
 * message or email -- not rendered in the app itself. Pure and client-side:
 * built entirely from one GET /modules?repo_root=... response, no new
 * backend endpoint (see CLAUDE.md's Phase 28 decision note for why that's
 * sufficient -- severity is approximated via the Stats page's own
 * KPI_TILES accents instead of a real check_type x severity matrix, which
 * isn't available without N+1 per-module fetches).
 */
export function buildHealthReportMarkdown({
  repoRoot,
  modules,
  generatedAt,
  origin,
}: {
  repoRoot: string;
  modules: ModuleSummary[];
  generatedAt: Date;
  origin: string;
}): string {
  const total = modules.length;

  const lines: string[] = [
    "# MageWiki health report",
    "",
    `**Repo:** \`${repoRoot}\``,
    `**Generated:** ${generatedAt.toISOString()}`,
  ];

  if (total === 0) {
    lines.push("", "No modules scanned under this repo yet.");
    return lines.join("\n") + "\n";
  }

  const lastScannedAt = modules
    .map((m) => new Date(m.last_scanned_at))
    .reduce((latest, scannedAt) => (scannedAt > latest ? scannedAt : latest));

  lines.push(
    `**Last scanned:** ${lastScannedAt.toISOString()} — this report reflects that scan, not a fresh one.`,
    "",
    "## Overview",
    "",
    `- ${total} module${total === 1 ? "" : "s"}`,
    `- ${percent(modules.filter((m) => m.enabled === true).length, total)} enabled`,
    `- ${percent(modules.filter((m) => m.has_readme).length, total)} with a README`,
    `- ${percent(modules.filter((m) => m.has_tests).length, total)} with tests`,
    `- ${percent(modules.filter((m) => m.has_module_doc).length, total)} with an AI-generated doc`,
    "",
  );

  // Fallback tiles get the same "warning" accent the Stats page's own
  // fallbackTiles use -- not a real severity, just "this check_type exists
  // but nobody's written it a dedicated tile yet."
  const tilesWithCounts = [
    ...KPI_TILES,
    /* v8 ignore start -- FALLBACK_CHECK_TYPES is empty today (every real
       check_type already has a KPI_TILES entry, same as stats/page.tsx's
       own identical fallbackTiles); kept so the NEXT check_type added
       without a dedicated tile still shows up here instead of vanishing. */
    ...FALLBACK_CHECK_TYPES.map((checkType) => ({
      label: prettifyCheckType(checkType),
      checkTypes: [checkType],
      accent: "warning" as const,
    })),
    /* v8 ignore stop */
  ]
    .map((tile) => ({ ...tile, value: tile.checkTypes.reduce((sum, ct) => sum + sumByCheckType(modules, ct), 0) }))
    .filter((tile) => tile.value > 0);

  lines.push("## Quality findings", "");
  if (tilesWithCounts.length === 0) {
    lines.push("No quality findings — clean fleet.", "");
  } else {
    for (const accent of ACCENT_ORDER) {
      const tilesForAccent = tilesWithCounts.filter((t) => t.accent === accent);
      if (tilesForAccent.length === 0) continue;
      lines.push(`### ${ACCENT_HEADINGS[accent]}`, "");
      for (const tile of tilesForAccent) {
        lines.push(`- **${tile.label}**: ${tile.value}`);
      }
      lines.push("");
    }
  }

  const riskiest = modules
    .map((m) => ({ module: m, total: totalFindings(m) }))
    .filter((r) => r.total > 0)
    .sort((a, b) => b.total - a.total)
    .slice(0, 5);

  lines.push("## Riskiest modules", "");
  if (riskiest.length === 0) {
    lines.push("No modules have any findings.");
  } else {
    for (const { module, total: findingTotal } of riskiest) {
      lines.push(`- [${module.name}](${origin}/modules/${module.id}) — ${findingTotal} finding${findingTotal === 1 ? "" : "s"}`);
    }
  }

  return lines.join("\n").trimEnd() + "\n";
}
