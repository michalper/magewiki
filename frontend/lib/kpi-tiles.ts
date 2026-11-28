import { CHECK_TYPES } from "@/components/quality-badges";

export type AccentLevel = "critical" | "warning" | "none";

// The curated, human-written KPI tiles — each names exactly which check_type(s)
// it summarizes (some fold several related ones into one tile, e.g. "Magento
// upgrade blockers" or "Cross-module conflicts"). checkTypes here is the single
// source of truth both the Stats page and the repo health report use to
// compute every total, AND to figure out which check_types still have no tile
// at all (see FALLBACK_CHECK_TYPES) — a new check_type is invisible here only
// if nobody adds it to one of these arrays, which previously happened twice in
// one session (PhpMetrics, then three more check types) before this fallback
// existed.
export const KPI_TILES: {
  label: string;
  checkTypes: string[];
  accent: AccentLevel;
  description: string;
}[] = [
  {
    label: "Hardcoded secrets",
    checkTypes: ["hardcoded_secret"],
    accent: "critical",
    description:
      "API keys, passwords, or tokens written directly in the code instead of a secure config. Anyone with code access can read them — fix urgently.",
  },
  {
    label: "Known vulnerabilities",
    checkTypes: ["security_advisory"],
    accent: "critical",
    description:
      "Third-party libraries with publicly disclosed security flaws (CVEs). Each one cites the advisory it matched.",
  },
  {
    label: "Deprecated usages",
    checkTypes: ["deprecated_annotation"],
    accent: "warning",
    description:
      "Code calling something Magento has marked for removal in a future version — works today, but will need updating before the next major upgrade.",
  },
  {
    label: "Composer issues",
    checkTypes: ["composer_completeness"],
    accent: "warning",
    description:
      "Problems with a module's own packaging metadata (Composer is Magento's package manager) — e.g. missing license info or test coverage declared incorrectly.",
  },
  {
    label: "Abandoned dependencies",
    checkTypes: ["abandoned_dependency"],
    accent: "warning",
    description:
      "Third-party libraries the maintainer has officially stopped supporting — no more fixes or security patches will ever come, even for new vulnerabilities.",
  },
  {
    label: "Outdated dependencies",
    checkTypes: ["outdated_dependency"],
    accent: "none",
    description: "Third-party libraries with a newer version available. Not urgent on its own, but worth tracking so upgrades don't pile up.",
  },
  {
    label: "Magento upgrade blockers",
    checkTypes: ["magento_php_incompatible", "magento_version_blocker"],
    accent: "critical",
    description:
      "Modules that would break outright on the latest Magento release (wrong PHP version or incompatible Magento package requirement) — these block an upgrade project until fixed.",
  },
  {
    label: "PHP static-analysis findings",
    checkTypes: ["phpstan_error", "phpmd_issue", "phpcs_violation", "php_compat_issue", "phpmetrics_issue"],
    accent: "warning",
    description:
      "Code-quality issues caught by automated PHP analysis tools (bugs, style violations, overly complex code, risky metrics) — a proxy for how much technical debt a module carries.",
  },
  {
    label: "Cross-module conflicts",
    checkTypes: [
      "plugin_conflict",
      "composer_conflict",
      "webapi_route_conflict",
      "db_schema_conflict",
      "circular_dependency",
      "preference_conflict",
      "cron_job_conflict",
      "graphql_field_conflict",
      "acl_resource_conflict",
      "indexer_id_conflict",
      "view_id_conflict",
      "missing_acl",
      "route_id_conflict",
      "frontname_conflict",
      "virtual_type_conflict",
      "widget_id_conflict",
      "menu_item_id_conflict",
      "cache_type_conflict",
      "email_template_id_conflict",
    ],
    accent: "warning",
    description:
      "Two modules silently fighting over the same plugin hook, Composer package version, REST route, database column, di.xml preference or virtualType, cron job code, GraphQL field, ACL resource id, indexer id, mview id, routes.xml route id/frontName, widget id, admin menu item id, cache type id, or email template id — a circular module.xml sequence that breaks setup:upgrade outright — or an admin controller declared with no ACL resource at all, reachable by any logged-in admin. Each shows up on every module involved.",
  },
  {
    label: "License risks",
    checkTypes: ["license_risk"],
    accent: "warning",
    description:
      "Modules declaring a strong-copyleft license (GPL/AGPL/SSPL) — bundling one into a commercial store may carry real redistribution obligations worth reviewing.",
  },
  {
    label: "PHPUnit test failures",
    checkTypes: ["phpunit_failure"],
    accent: "warning",
    description:
      "Failing tests from a module's own Test/Unit/ suite, actually executed via its own vendor/bin/phpunit — only for modules that ship a standalone-runnable phpunit setup.",
  },
];

const _GROUPED_CHECK_TYPES = new Set(KPI_TILES.flatMap((t) => t.checkTypes));

// Any check_type CHECK_TYPES knows about but no KPI_TILES entry claims gets a
// plain, auto-generated tile instead of silently having no Stats/report
// representation at all — the actual fix for the bug class above. A new
// check_type can still get a hand-written label/description/grouping by
// adding it to KPI_TILES like any other; this only guarantees it's never
// invisible before someone does.
export const FALLBACK_CHECK_TYPES = CHECK_TYPES.map((c) => c.key).filter((key) => !_GROUPED_CHECK_TYPES.has(key));

export function prettifyCheckType(checkType: string): string {
  const words = checkType.split("_").join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
