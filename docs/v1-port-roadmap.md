# Porting ideas from v1 into MageWiki-AI

The author previously built a PHP tool for his employer Cognize to track Magento-module quality
across many clients' GitLab repos — call it "v1." MageWiki-AI is the from-scratch, open-source
**Python** rewrite — "v2." This document is the result of a one-time review of v1's source, docs,
and UI (2026-11-06) to decide which of its proven, production-tested ideas are worth porting.

**IP boundary.** v1 is Cognize's property and its data contains real client names, Jira keys,
GitLab groups, and a client-environments API. This document, and anything built from it, ports
**concepts and architecture only** — no copied PHP code, no client-identifying data, no mention
of v1's actual name. This matches CLAUDE.md's standing rule that MageWiki's repo and history
never contain confidential client code.

**Curation, not a 1:1 port.** v1 was built for a consultancy watching many *other companies'*
repos and filing *their* Jira tickets. Several of its features are Cognize-internal plumbing with
no open-source equivalent and are excluded outright below, not just deferred.

## Feature inventory and verdicts

| v1 feature | Verdict | Why |
|---|---|---|
| `composer.json` completeness linter | **Port — Phase 9** | Pure JSON heuristic, same tier as the existing `composer_json.py` parser. |
| README-presence check | **Port — Phase 9** | Trivial file-existence check. |
| `@deprecated` annotation scanner | **Port — Phase 9** | tree-sitter-php AST walk; reuses the exact pattern already in `php_classes.py`. |
| Hardcoded-secrets regex scanner | **Port — Phase 9** | Pure regex over source text, zero subprocess, zero new dependency. Blocking severity by default in v1. |
| Test-presence detection | **Port — Phase 9** | Directory/filename heuristic (`Test(s)/`, `*Test.php`, `phpunit.xml`), no execution. |
| Badge/pill severity system, KPI donut-ring stat tiles, dense sortable/filterable table, accordion detail rows | **Port — Phase 9 (UI)** | Proven, scannable dashboard patterns; reimplemented with shadcn/Tailwind, not copied Bootstrap/Tabler markup. |
| CVE / security-advisory check | **Port — Phase 10** | Designed in full below. High-value, proven in production. |
| Abandoned/outdated-dependency check | **Port — Phase 10** | Shares the Packagist client + cache table the CVE check needs anyway; non-blocking by default. |
| Cross-repo "fleet" stats/health view | **Port — Phase 11** | `Module.repo_root` already makes multiple repos coexist in one DB today — this is mostly a new aggregation query + a repos-list page, not a schema change. Scoped down: no GitLab-API project discovery, no Jira, no "client" concept — just the repos the user has pointed MageWiki at. |
| PHPStan / PHPMD / phpcs (`magento/magento-coding-standard`) / PhpMetrics / Rector (PHP-compat + rule sets) | **Own future phase — Phase 12, needs explicit sign-off** | All proven, but every one shells out to real PHP tooling. MageWiki's backend is deliberately Python-only (CLAUDE.md chose tree-sitter-php specifically to avoid needing a PHP runtime); adding these means a PHP+Composer toolchain in the image or a sidecar — a real architecture change, not a drive-by addition. |
| Jira ticket-creation deep link | **Skip** | Cognize-internal tool choice; no open-source audience. |
| Dashboard API (client environments, VPN) | **Skip** | Entirely Cognize-internal infrastructure. |
| Satis internal composer mirror sync | **Skip** | Cognize-internal. |
| Client-Jira-key import from a sister internal system | **Skip** | Cognize-internal. |
| Dead-branch detection | **Skip** | v1 treats each *module* as its own GitLab repo with its own branches. MageWiki scans modules as subdirectories of one mounted store (`app/code`, `vendor`) — there's no per-module git history to inspect. Doesn't transfer. |
| Dedicated "Keywords" page | **Skip** | MageWiki already has a richer analog: the AI+parser `tags` system in `module_docs`. |

## CVE / security-advisory check — detailed design (Phase 10)

**How v1 does it** (confirmed by reading its security-advisory checker and Packagist client
classes): for every third-party `require`/`require-dev` package, GET
`https://packagist.org/api/security-advisories/?packages[]={vendor/package}` — Packagist's own
public, unauthenticated aggregation of the FriendsOfPHP/security-advisories feed (not OSV.dev, not
a bespoke database). Cache the response 24h. Then use `composer/semver`'s interval-overlap check
between the module's **declared version constraint** and each advisory's `affectedVersions` — a
package is only flagged if the ranges actually intersect, never on name match alone. Defaults to
blocking severity (alongside PHP-incompatibility, the only two categories v1 treats as real
upgrade blockers rather than tech debt).

**Porting to MageWiki** (Postgres instead of SQLite, Python instead of PHP):

- **Gap found while scoping this**: `ComposerResult` / `parse_composer_json()`
  (`backend/app/scanner/composer_json.py`) currently extracts only `name`/`type`/`license` — no
  `require`/`require-dev` data at all. `ModuleDependency` (`backend/app/models.py`) is a different
  concept (Magento `module.xml` `<sequence>` deps, keyed by Magento module name, no version info).
  Phase 10 needs a new extraction step plus a new table, e.g.
  `ComposerPackageRequirement(module_id, package_name, constraint, is_dev)`, populated in
  `orchestrator.py` alongside the existing `ModuleDependency` persistence.
- **Cache table**: a Postgres table mirroring v1's Packagist-response cache (key, response JSON,
  fetched_at), TTL 24h, shared between the CVE check and the abandoned/outdated check.
- **Semver overlap**: Composer's version-constraint grammar isn't identical to PyPI's — this needs
  a real interval-overlap implementation in Python, not a one-line library swap assumed to match
  Composer's grammar.
- **Anti-hallucination fit**: a pure parser/external-API fact, no LLM involved — fits CLAUDE.md's
  "facts come from parsers" rule directly. Store with `source: "parser"` like other deterministic
  signals; surface in `module_docs` as a new `security_advisories` field alongside `risks`.
- **Severity**: blocking by default, matching v1's production judgment that a known CVE should
  block an upgrade-readiness verdict, once MageWiki has an equivalent verdict concept.

## UI/UX patterns to port (Phase 9)

v1's UI (Tabler/Bootstrap 5, server-rendered Twig) demonstrated several effective, reusable
patterns worth reimplementing natively in Next.js/Tailwind/shadcn — not copying the Bootstrap
markup or CSS:

- **Severity badge/pill system**: tinted-background pills (`bg-{color}-lt` in Tabler) —
  red = blocking, orange = warning, green = ok, gray = no data — applied consistently across
  every table, chip, and detail panel. shadcn's `Badge` component with custom color variants is
  the direct equivalent.
- **KPI donut/ring stat tiles**: a grid of small ring charts, each with a big central count and a
  color-coded legend, used both as hero-sized summary tiles and as a repeated small-multiple wall
  (one ring per check category) — a single reusable "ring + legend" component at two sizes. Pick a
  charting library (Recharts or visx) and go through the `dataviz` skill when this phase starts.
- **Dense sortable/filterable table** with a dedicated filter bar (search + several dropdown
  facets + clear button) above it, and **accordion-style expand-in-place detail rows** (click a
  row to reveal a shaded sub-panel with the full issue list, capped at ~20 + "N more") instead of
  navigating to a separate detail page for every drill-down.
- **Dark/light theme toggle**, persisted client-side — straightforward with `next-themes`, which
  the shadcn ecosystem already expects.

## New phases to append to CLAUDE.md's phase plan

| Phase | Goal | Done when |
|---|---|---|
| 9 | Parser-only quality checks (composer completeness, README presence, `@deprecated`, hardcoded secrets, test presence) + badge/KPI-ring UI foundation | New checks show up as badges on the module list and a stats page with KPI rings |
| 10 | Dependency intelligence: CVE/security-advisory check + abandoned/outdated check | A module with a known-vulnerable dependency shows a blocking CVE badge citing the advisory |
| 11 | Multi-repo fleet view | A repos-list page aggregates health across every repo MageWiki has scanned |
| 12 | PHP static-analysis toolchain (PHPStan/PHPMD/phpcs/PhpMetrics/Rector) — optional/stretch, needs explicit sign-off before starting given the PHP-toolchain architecture change | Equivalent scanners run against a module and their findings show up as badges |
| 13 | One cloud (GCP or Azure) via Terraform, managed Postgres + pgvector *(renumbered from Phase 9 — still deferred, no cloud account/funds)* | Public demo deployment |
