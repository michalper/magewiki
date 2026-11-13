import { SeverityBadge, type Severity } from "@/components/severity-badge";

// Single source of truth for every module_quality_findings check type —
// was an independently re-typed list of fields/badges/sums in the backend's
// response models (3 construction sites) and 3 frontend pages (modules,
// repos, stats). Adding a new check type now means one row here.
export const CHECK_TYPES: { key: string; severity: Severity; label: (n: number) => string }[] = [
  { key: "hardcoded_secret", severity: "blocking", label: (n) => `${n} secret${n === 1 ? "" : "s"}` },
  { key: "security_advisory", severity: "blocking", label: (n) => `${n} CVE` },
  { key: "composer_completeness", severity: "warning", label: (n) => `${n} composer` },
  { key: "deprecated_annotation", severity: "warning", label: (n) => `${n} deprecated` },
  { key: "abandoned_dependency", severity: "warning", label: (n) => `${n} abandoned` },
  { key: "outdated_dependency", severity: "info", label: (n) => `${n} outdated` },
  { key: "phpstan_error", severity: "warning", label: (n) => `${n} phpstan` },
  { key: "phpmd_issue", severity: "warning", label: (n) => `${n} phpmd` },
  { key: "phpcs_violation", severity: "warning", label: (n) => `${n} phpcs` },
  { key: "php_compat_issue", severity: "warning", label: (n) => `${n} php-compat` },
  { key: "magento_php_incompatible", severity: "blocking", label: (n) => `${n} magento-php` },
  { key: "magento_version_blocker", severity: "blocking", label: (n) => `${n} magento-upgrade` },
  { key: "plugin_conflict", severity: "warning", label: (n) => `${n} plugin-conflict${n === 1 ? "" : "s"}` },
  { key: "phpmetrics_issue", severity: "warning", label: (n) => `${n} phpmetrics` },
  { key: "composer_conflict", severity: "warning", label: (n) => `${n} composer-conflict${n === 1 ? "" : "s"}` },
  { key: "webapi_route_conflict", severity: "warning", label: (n) => `${n} route-conflict${n === 1 ? "" : "s"}` },
  { key: "db_schema_conflict", severity: "warning", label: (n) => `${n} schema-conflict${n === 1 ? "" : "s"}` },
  { key: "circular_dependency", severity: "warning", label: (n) => `${n} circular-dep${n === 1 ? "" : "s"}` },
  { key: "license_risk", severity: "warning", label: (n) => `${n} license-risk${n === 1 ? "" : "s"}` },
  { key: "phpunit_failure", severity: "warning", label: (n) => `${n} test-failure${n === 1 ? "" : "s"}` },
  { key: "preference_conflict", severity: "warning", label: (n) => `${n} preference-conflict${n === 1 ? "" : "s"}` },
  { key: "cron_job_conflict", severity: "warning", label: (n) => `${n} cron-conflict${n === 1 ? "" : "s"}` },
  { key: "graphql_field_conflict", severity: "warning", label: (n) => `${n} graphql-conflict${n === 1 ? "" : "s"}` },
  { key: "acl_resource_conflict", severity: "warning", label: (n) => `${n} acl-conflict${n === 1 ? "" : "s"}` },
  { key: "missing_acl", severity: "warning", label: (n) => `${n} missing-acl` },
  { key: "indexer_id_conflict", severity: "warning", label: (n) => `${n} indexer-conflict${n === 1 ? "" : "s"}` },
  { key: "view_id_conflict", severity: "warning", label: (n) => `${n} view-conflict${n === 1 ? "" : "s"}` },
  // "route-id-conflict"/"frontname-conflict", not "route-conflict" --
  // webapi_route_conflict (REST routes) already uses that label, and these
  // are a genuinely different file (routes.xml, not webapi.xml).
  { key: "route_id_conflict", severity: "warning", label: (n) => `${n} route-id-conflict${n === 1 ? "" : "s"}` },
  { key: "frontname_conflict", severity: "warning", label: (n) => `${n} frontname-conflict${n === 1 ? "" : "s"}` },
  // "virtualtype-conflict", not "virtual-type-conflict" or "preference-
  // conflict" -- a different di.xml element than <preference>, so it needs
  // its own distinct label even though both live in the same file.
  {
    key: "virtual_type_conflict",
    severity: "warning",
    label: (n) => `${n} virtualtype-conflict${n === 1 ? "" : "s"}`,
  },
  { key: "widget_id_conflict", severity: "warning", label: (n) => `${n} widget-conflict${n === 1 ? "" : "s"}` },
];

export function sumFindingCounts(findingCounts: Record<string, number>): number {
  return Object.values(findingCounts).reduce((sum, n) => sum + n, 0);
}

export function QualityBadges({ findingCounts }: { findingCounts: Record<string, number> }) {
  if (sumFindingCounts(findingCounts) === 0) return <SeverityBadge severity="ok">clean</SeverityBadge>;
  return (
    <div className="flex flex-wrap gap-1">
      {CHECK_TYPES.map(({ key, severity, label }) => {
        const n = findingCounts[key] ?? 0;
        if (n === 0) return null;
        return (
          <SeverityBadge key={key} severity={severity}>
            {label(n)}
          </SeverityBadge>
        );
      })}
    </div>
  );
}
