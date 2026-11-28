import { Info, Loader2 } from "lucide-react";
import { type ReactNode, useState } from "react";

import { FindingMessage } from "@/components/finding-message";
import { SeverityBadge, SEVERITY_ORDER, type Severity } from "@/components/severity-badge";
import { apiFetch } from "@/lib/api";

type Finding = {
  check_type: string;
  severity: string;
  file_path: string | null;
  line: number | null;
  message: string;
};

async function fetchRemediation(moduleId: number | string, finding: Finding): Promise<string> {
  const response = await apiFetch<{ remediation: string }>(`/modules/${moduleId}/findings/remediation`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      check_type: finding.check_type,
      file_path: finding.file_path,
      line: finding.line,
      message: finding.message,
    }),
  });
  return response.remediation;
}

// Click-to-reveal, not hover-to-fetch -- this is a real, billable LLM call
// (see app/analyzer/remediation.py), and a hover tooltip risks firing one on
// incidental mouse movement. Fetched once per finding per page load; the
// backend's own cache makes a repeat click free, but there's no need to
// re-fetch/re-render past the first successful reveal.
type RemediationState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "done"; text: string }
  | { status: "error"; message: string };

function RemediationButton({
  moduleId,
  finding,
  state,
  onStateChange,
}: {
  moduleId: number | string;
  finding: Finding;
  state: RemediationState;
  onStateChange: (state: RemediationState) => void;
}) {
  if (state.status !== "idle") return null;

  async function handleClick() {
    onStateChange({ status: "loading" });
    try {
      const text = await fetchRemediation(moduleId, finding);
      onStateChange({ status: "done", text });
    } catch (err) {
      onStateChange({ status: "error", message: err instanceof Error ? err.message : "Failed to load." });
    }
  }

  return (
    <button
      type="button"
      className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground/70 hover:text-foreground"
      onClick={() => {
        void handleClick();
      }}
    >
      <Info className="size-3" />
      Explain
    </button>
  );
}

function RemediationResult({ state }: { state: RemediationState }) {
  if (state.status === "loading") {
    return (
      <p className="flex items-center gap-1 text-xs text-muted-foreground mt-1">
        <Loader2 className="size-3 animate-spin" /> Loading...
      </p>
    );
  }
  if (state.status === "done") {
    return <p className="text-sm text-muted-foreground mt-1">{state.text}</p>;
  }
  if (state.status === "error") {
    return <p className="text-sm text-destructive mt-1">{state.message}</p>;
  }
  return null;
}

function FindingItem({ finding, moduleId }: { finding: Finding; moduleId?: number | string }) {
  const [remediationState, setRemediationState] = useState<RemediationState>({ status: "idle" });

  return (
    <li className="space-y-0.5">
      <div className="flex items-center gap-2">
        <SeverityBadge severity={finding.severity as Severity}>{finding.severity}</SeverityBadge>
        <span className="font-mono text-muted-foreground whitespace-nowrap">
          {finding.file_path}
          {finding.line ? `:${finding.line}` : ""}
        </span>
        {moduleId !== undefined && (
          <RemediationButton
            moduleId={moduleId}
            finding={finding}
            state={remediationState}
            onStateChange={setRemediationState}
          />
        )}
      </div>
      <div>
        <FindingMessage message={finding.message} />
      </div>
      {moduleId !== undefined && <RemediationResult state={remediationState} />}
    </li>
  );
}

/**
 * Sorts findings by severity and renders the most severe `limit` of them --
 * shared by the modules list (expanded row, a short preview) and the module
 * detail page (a longer preview with a CSV export button). `footer` renders
 * only when there are more findings than `limit`, so each caller supplies
 * its own "see the rest" affordance (a link to the full detail page, or a
 * pointer to the detail page's own CSV export) without this component
 * needing to know which one makes sense where.
 *
 * `moduleId` is optional: pass it for real, already-scanned findings (the
 * modules list and the module detail page) to show an "Explain" button; omit
 * it for hypothetical findings that were never persisted as a real
 * ModuleQualityFinding row (e.g. the upgrade-impact page's predicted
 * findings, Phase 27 -- the backend endpoint always 404s for those, since it
 * verifies the finding against a real row first).
 */
export function FindingsPreviewList({
  findings,
  limit,
  footer,
  moduleId,
}: {
  findings: Finding[];
  limit: number;
  footer: ReactNode;
  moduleId?: number | string;
}) {
  const preview = [...findings]
    .sort((a, b) => SEVERITY_ORDER[a.severity as Severity] - SEVERITY_ORDER[b.severity as Severity])
    .slice(0, limit);
  return (
    <>
      <ul className="text-sm space-y-2">
        {preview.map((f, i) => (
          <FindingItem key={i} finding={f} moduleId={moduleId} />
        ))}
      </ul>
      {findings.length > limit && footer}
    </>
  );
}
