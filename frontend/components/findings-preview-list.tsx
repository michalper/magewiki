import type { ReactNode } from "react";

import { FindingMessage } from "@/components/finding-message";
import { SeverityBadge, SEVERITY_ORDER, type Severity } from "@/components/severity-badge";

type Finding = {
  severity: string;
  file_path: string | null;
  line: number | null;
  message: string;
};

/**
 * Sorts findings by severity and renders the most severe `limit` of them --
 * shared by the modules list (expanded row, a short preview) and the module
 * detail page (a longer preview with a CSV export button). `footer` renders
 * only when there are more findings than `limit`, so each caller supplies
 * its own "see the rest" affordance (a link to the full detail page, or a
 * pointer to the detail page's own CSV export) without this component
 * needing to know which one makes sense where.
 */
export function FindingsPreviewList({
  findings,
  limit,
  footer,
}: {
  findings: Finding[];
  limit: number;
  footer: ReactNode;
}) {
  const preview = [...findings]
    .sort((a, b) => SEVERITY_ORDER[a.severity as Severity] - SEVERITY_ORDER[b.severity as Severity])
    .slice(0, limit);
  return (
    <>
      <ul className="text-sm space-y-2">
        {preview.map((f, i) => (
          <li key={i} className="space-y-0.5">
            <div className="flex items-center gap-2">
              <SeverityBadge severity={f.severity as Severity}>{f.severity}</SeverityBadge>
              <span className="font-mono text-muted-foreground whitespace-nowrap">
                {f.file_path}
                {f.line ? `:${f.line}` : ""}
              </span>
            </div>
            <div>
              <FindingMessage message={f.message} />
            </div>
          </li>
        ))}
      </ul>
      {findings.length > limit && footer}
    </>
  );
}
