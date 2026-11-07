"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import ReactMarkdown, { type Components } from "react-markdown";
import { Badge } from "@/components/ui/badge";
import { EnabledBadge } from "@/components/enabled-badge";
import { SeverityBadge, SEVERITY_ORDER, type Severity } from "@/components/severity-badge";
import { StateBadge } from "@/components/state-badge";
import { Button } from "@/components/ui/button";
import { apiFetch, apiUrl } from "@/lib/api";
import { downloadCsv, toCsv } from "@/lib/csv";
import type { components } from "@/lib/api-types";

type ModuleDetail = components["schemas"]["ModuleDetail"];
type ModuleSummary = components["schemas"]["ModuleSummary"];

const PREVIEW_FINDING_COUNT = 10;

// A README's own "## Dependencies" list item is plain AI-written markdown
// text (e.g. "Magento_Sales"), not the structured dependencies array the
// "Depends on:" line above already links — extracts it to match against
// idByName the same way, without disturbing richer list items (Features,
// Risks) that mix bold text with prose.
function plainListItemText(children: ReactNode): string | null {
  if (typeof children === "string") return children.trim();
  if (Array.isArray(children) && children.length === 1 && typeof children[0] === "string") {
    return children[0].trim();
  }
  return null;
}

const RISK_SEVERITY_CLASSES: Record<string, string> = {
  high: "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-400",
  medium: "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-400",
  low: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-400",
};

// A README's own "## Risks" list item leads with a bold "[high]"/"[medium]"/
// "[low]" tag (the module_synthesis_v1 prompt's own convention) — render it
// as a colored badge, same visual language as quality findings' severity
// badges, instead of leaving it as plain bold bracketed text.
function riskSeverityFromStrongText(children: ReactNode): string | null {
  if (typeof children !== "string") return null;
  const match = /^\[(high|medium|low)\]$/i.exec(children.trim());
  return match ? match[1].toLowerCase() : null;
}

// README markdown always follows the module_synthesis_v1 prompt's fixed
// template (Description, Features, Integrations, Tags, Risks, For PMs, For
// developers, Dependencies, Plugins, Observers, ...) — splitting on "## "
// headings turns the single scroll of text into one card per section, same
// visual language as the Quality findings card below it.
function splitReadmeIntoSections(markdown: string): { title: string; body: string }[] {
  const lines = markdown.split("\n");
  const sections: { title: string; body: string }[] = [];
  let title = "Overview";
  let body: string[] = [];
  for (const line of lines) {
    const heading = /^##\s+(.+)$/.exec(line);
    if (heading) {
      sections.push({ title, body: body.join("\n").trim() });
      title = heading[1].trim();
      body = [];
    } else if (!/^#\s+/.test(line)) {
      // Drop the "# Module (composer/name)" h1 — the page header already
      // shows the module name, and composer name is shown a few lines up.
      body.push(line);
    }
  }
  sections.push({ title, body: body.join("\n").trim() });
  return sections.filter((s) => s.body.length > 0);
}

function sectionSlug(title: string): string {
  return `readme-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}`;
}

// Long sections (Features/Risks with 20+ items on a real large module) made
// the page itself a new wall of text once split into cards — collapse
// anything past a rough height budget behind a "Show more" toggle, rather
// than counting list items, so it works for prose sections (For developers)
// the same way it works for bullet lists.
const COLLAPSE_THRESHOLD_CHARS = 600;

function ReadmeSectionCard({
  title,
  body,
  components,
}: {
  title: string;
  body: string;
  components: Components;
}) {
  const [expanded, setExpanded] = useState(false);
  const collapsible = body.length > COLLAPSE_THRESHOLD_CHARS;
  return (
    <div id={sectionSlug(title)} className="rounded-2xl bg-card p-5 shadow-sm scroll-mt-20">
      <h2 className="text-lg font-medium mb-3">{title}</h2>
      <div className={`text-sm relative ${collapsible && !expanded ? "max-h-48 overflow-hidden" : ""}`}>
        <ReactMarkdown components={components}>{body}</ReactMarkdown>
        {collapsible && !expanded && (
          <div className="absolute bottom-0 inset-x-0 h-16 bg-gradient-to-t from-card to-transparent" />
        )}
      </div>
      {collapsible && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-sm text-primary hover:underline mt-2"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

// No Tailwind typography plugin in this project — style the rendered README
// Markdown directly instead of pulling in another dependency for it.
function readmeMarkdownComponents(idByName: Map<string, number>): Components {
  return {
    h1: (props) => <h3 className="text-base font-semibold mt-4 mb-2 first:mt-0" {...props} />,
    h2: (props) => <h3 className="text-base font-semibold mt-4 mb-2 first:mt-0" {...props} />,
    h3: (props) => <h4 className="text-sm font-semibold mt-3 mb-1.5 first:mt-0" {...props} />,
    p: (props) => <p className="mb-3 last:mb-0 leading-relaxed" {...props} />,
    ul: (props) => <ul className="list-disc pl-5 mb-3 space-y-1" {...props} />,
    ol: (props) => <ol className="list-decimal pl-5 mb-3 space-y-1" {...props} />,
    li: ({ children, ...props }) => {
      const text = plainListItemText(children);
      const depId = text ? idByName.get(text) : undefined;
      if (depId !== undefined) {
        return (
          <li {...props}>
            <Link href={`/modules/${depId}`} className="text-primary hover:underline">
              {text}
            </Link>
          </li>
        );
      }
      return <li {...props}>{children}</li>;
    },
    a: (props) => <a className="text-primary hover:underline" {...props} />,
    code: (props) => <code className="bg-background/60 rounded px-1 py-0.5 font-mono text-xs" {...props} />,
    strong: ({ children, ...props }) => {
      const severity = riskSeverityFromStrongText(children);
      if (severity) {
        return (
          <span
            className={`inline-block rounded px-1.5 py-0.5 text-xs font-semibold uppercase mr-1.5 ${RISK_SEVERITY_CLASSES[severity]}`}
          >
            {severity}
          </span>
        );
      }
      return (
        <strong className="font-semibold" {...props}>
          {children}
        </strong>
      );
    },
  };
}

function downloadFindingsCsv(moduleName: string, findings: ModuleDetail["quality_findings"]) {
  const headers = ["check_type", "severity", "file_path", "line", "message"];
  const rows = findings.map((f) => [f.check_type, f.severity, f.file_path, f.line, f.message]);
  downloadCsv(`${moduleName}-findings-${new Date().toISOString().slice(0, 10)}.csv`, toCsv(headers, rows));
}

async function fetchModule(id: string): Promise<ModuleDetail> {
  return apiFetch(`/modules/${id}`);
}

async function fetchModules(): Promise<ModuleSummary[]> {
  return apiFetch("/modules");
}

async function fetchReadme(id: string): Promise<string | null> {
  // apiFetch always parses JSON and can't special-case 404 as "not an error" —
  // this is the one fetch in the app that returns plain text and treats a
  // missing README as a valid, non-error result, so it stays bespoke.
  const res = await fetch(`${apiUrl()}/modules/${id}/readme`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API responded with ${res.status}`);
  return res.text();
}

export default function ModuleDetailClient({ id }: { id: string }) {
  const moduleQuery = useQuery({ queryKey: ["module", id], queryFn: () => fetchModule(id) });
  const readmeQuery = useQuery({ queryKey: ["module-readme", id], queryFn: () => fetchReadme(id) });
  // Same queryKey the Modules list page uses, so navigating here from there is
  // an instant cache hit rather than a second full-fleet fetch.
  const modulesQuery = useQuery({ queryKey: ["modules"], queryFn: fetchModules });

  const repoRoot = moduleQuery.data?.repo_root;
  const idByName = new Map<string, number>();
  if (modulesQuery.data && repoRoot) {
    for (const m of modulesQuery.data) {
      if (m.repo_root === repoRoot) idByName.set(m.name, m.id);
    }
  }

  return (
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-4xl mx-auto w-full">
      <Link href="/modules" className="text-sm text-primary hover:underline self-start">
        ← All modules
      </Link>

      {moduleQuery.isLoading && <p>Loading...</p>}
      {moduleQuery.isError && <p className="text-destructive">Failed to load module.</p>}

      {moduleQuery.data && (
        <>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{moduleQuery.data.name}</h1>
            <EnabledBadge enabled={moduleQuery.data.enabled} />
            <StateBadge state={moduleQuery.data.state} />
            {moduleQuery.data.tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
            <SeverityBadge severity={moduleQuery.data.has_readme ? "ok" : "none"}>
              {moduleQuery.data.has_readme ? "README" : "no README"}
            </SeverityBadge>
            <SeverityBadge severity={moduleQuery.data.has_tests ? "ok" : "none"}>
              {moduleQuery.data.has_tests ? "tests" : "no tests"}
            </SeverityBadge>
          </div>
          <Link href={`/modules/${id}/graph`} className="text-sm text-primary hover:underline self-start">
            View dependency graph →
          </Link>
          <p className="text-sm text-muted-foreground">
            Last scanned {new Date(moduleQuery.data.last_scanned_at).toLocaleString()} — composer:{" "}
            {moduleQuery.data.composer_name ?? "—"} — version: {moduleQuery.data.setup_version ?? "—"}
          </p>

          {moduleQuery.data.dependencies.length > 0 && (
            <div className="text-sm flex flex-wrap items-center gap-x-1">
              <span className="font-medium">Depends on:</span>
              {moduleQuery.data.dependencies.map((dep, i) => {
                const depId = idByName.get(dep);
                return (
                  <span key={dep}>
                    {depId !== undefined ? (
                      <Link href={`/modules/${depId}`} className="text-primary hover:underline">
                        {dep}
                      </Link>
                    ) : (
                      <span className="text-muted-foreground">{dep}</span>
                    )}
                    {i < moduleQuery.data.dependencies.length - 1 ? "," : ""}
                  </span>
                );
              })}
            </div>
          )}

          <div id="readme" className="flex flex-col gap-4 scroll-mt-20">
            {readmeQuery.isLoading && (
              <div className="rounded-2xl bg-card p-5 shadow-sm">
                <p className="text-sm text-muted-foreground">Loading...</p>
              </div>
            )}
            {readmeQuery.data === null && (
              <div className="rounded-2xl bg-card p-5 shadow-sm">
                <p className="text-sm text-muted-foreground">This module has not been analyzed yet.</p>
              </div>
            )}
            {readmeQuery.data &&
              (() => {
                const sections = splitReadmeIntoSections(readmeQuery.data);
                const components = readmeMarkdownComponents(idByName);
                return (
                  <>
                    {sections.length > 1 && (
                      <div className="flex flex-wrap gap-1.5">
                        {sections.map((section) => (
                          <a
                            key={section.title}
                            href={`#${sectionSlug(section.title)}`}
                            className="text-xs rounded-full border border-border px-2.5 py-1 text-muted-foreground hover:text-foreground hover:border-foreground/40"
                          >
                            {section.title}
                          </a>
                        ))}
                      </div>
                    )}
                    {sections.map((section) => (
                      <ReadmeSectionCard
                        key={section.title}
                        title={section.title}
                        body={section.body}
                        components={components}
                      />
                    ))}
                  </>
                );
              })()}
          </div>

          {moduleQuery.data.quality_findings.length > 0 && (
            <div className="rounded-2xl bg-card p-5 shadow-sm">
              <div className="flex items-center justify-between gap-2 mb-3">
                <h2 className="text-lg font-medium">
                  Quality findings{" "}
                  <span className="text-sm font-normal text-muted-foreground">
                    (most severe {Math.min(PREVIEW_FINDING_COUNT, moduleQuery.data.quality_findings.length)} of{" "}
                    {moduleQuery.data.quality_findings.length})
                  </span>
                </h2>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => downloadFindingsCsv(moduleQuery.data!.name, moduleQuery.data!.quality_findings)}
                >
                  Export findings CSV
                </Button>
              </div>
              <ul className="text-sm space-y-2">
                {[...moduleQuery.data.quality_findings]
                  .sort((a, b) => SEVERITY_ORDER[a.severity as Severity] - SEVERITY_ORDER[b.severity as Severity])
                  .slice(0, PREVIEW_FINDING_COUNT)
                  .map((f, i) => (
                    <li key={i} className="flex items-center gap-2 overflow-x-auto">
                      <SeverityBadge severity={f.severity as Severity}>{f.severity}</SeverityBadge>
                      <span className="font-mono text-muted-foreground shrink-0 whitespace-nowrap">
                        {f.file_path}
                        {f.line ? `:${f.line}` : ""}
                      </span>
                      <span className="whitespace-nowrap">{f.message}</span>
                    </li>
                  ))}
                {moduleQuery.data.quality_findings.length > PREVIEW_FINDING_COUNT && (
                  <li className="text-muted-foreground">
                    +{moduleQuery.data.quality_findings.length - PREVIEW_FINDING_COUNT} more — use &ldquo;Export
                    findings CSV&rdquo; above for the full set
                  </li>
                )}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}
