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

**Review depth.** The first pass (three parallel agents: docs, scanner source, UI) covered the
core quality-scanner architecture and dashboard thoroughly, but left `src/Testing`, `src/Api`,
`src/Maintenance`, `src/Usage`, the full changelog, and the deployment/ops files only partially
read. A second follow-up pass (three more agents) closed those gaps; findings are folded into the
table and the new "Additional findings" section below.

## Feature inventory and verdicts

| v1 feature | Verdict | Why |
|---|---|---|
| `composer.json` completeness linter | **Port — Phase 9** | Pure JSON heuristic, same tier as the existing `composer_json.py` parser. |
| README-presence check | **Port — Phase 9** | Trivial file-existence check. |
| `@deprecated` annotation scanner | **Port — Phase 9** | tree-sitter-php AST walk; reuses the exact pattern already in `php_classes.py`. |
| Hardcoded-secrets regex scanner | **Port — Phase 9** | Pure regex over source text, zero subprocess, zero new dependency. Blocking severity by default in v1. |
| Test-presence detection | **Port — Phase 9** | Directory/filename heuristic (`Test(s)/`, `*Test.php`, `phpunit.xml`), no execution. |
| Badge/pill severity system, KPI donut-ring stat tiles, dense sortable/filterable table, accordion detail rows | **Port — Phase 9 (UI)** | Proven, scannable dashboard patterns; reimplemented with shadcn/Tailwind, not copied Bootstrap/Tabler markup. |
| CSV export of a module/client report | **Port — Phase 9 (UI)** | Cheap, generic "export current table view as CSV" button — no Cognize-specific data needed, directly useful for a solo user sharing a report. |
| CVE / security-advisory check | **Port — Phase 10** | Designed in full below. High-value, proven in production. |
| Abandoned/outdated-dependency check | **Port — Phase 10** | Shares the Packagist client + cache table the CVE check needs anyway; non-blocking by default. |
| Cross-repo "fleet" stats/health view | **Port — Phase 11** | `Module.repo_root` already makes multiple repos coexist in one DB today — this is mostly a new aggregation query + a repos-list page, not a schema change. Scoped down: no GitLab-API project discovery, no Jira, no "client" concept — just the repos the user has pointed MageWiki at. If a "used in N repos" count is added, dedupe by repo — v1's own equivalent badge counts raw usage rows (which can double-count a repo scanned on more than one branch) rather than distinct repos, a known subtlety worth not repeating. |
| PHPStan / PHPMD / phpcs (`magento/magento-coding-standard`) / PhpMetrics / Rector (PHP-compat + rule sets) | **Own future phase — Phase 12, needs explicit sign-off** | All proven, but every one shells out to real PHP tooling. MageWiki's backend is deliberately Python-only (CLAUDE.md chose tree-sitter-php specifically to avoid needing a PHP runtime); adding these means a PHP+Composer toolchain in the image or a sidecar — a real architecture change, not a drive-by addition. **Crucially, none of these execute the scanned module's own code** — they only parse/analyze it statically, same risk class as today's tree-sitter scanning. |
| Real PHPUnit test execution (clone → `composer install` → `phpunit`, with a PHP-version-fallback sidecar for old modules) | **Deferred — needs its own explicit decision, not bundled into Phase 12** | A materially different risk class from every other scanner above: this *runs* the scanned module's own code (and its dependencies'), not just parses it. v1's own isolation is weak — a temp dir + timeouts + memory caps, no container/sandbox per run — and CLAUDE.md's "scanned code is never modified" principle has never had to consider "scanned code is executed" before. If this is ever wanted, it needs a real sandbox (e.g. a disposable per-run container) designed deliberately, not v1's isolation copied as-is. See details below. |
| Google-OAuth login restricted to a company email domain, with an explicit `AUTH_DISABLED`/`AUTH_DISABLED_ACK` kill-switch | **Skip for now, revisit at Phase 13** | Cognize's domain-restricted login has no open-source analog, but MageWiki has no auth at all today, which is fine for a local/demo tool — except Phase 13's public cloud demo will let anyone burn the `LLM_MONTHLY_BUDGET_USD` budget on chat queries. Worth a lightweight access gate (not full OAuth) when Phase 13 actually starts. |
| Tokenized external read API (`/api/stats`, `/api/clients`, `/api/usage.json`) for a third-party consumer | **Skip** | Built for one specific internal consumer app at Cognize; MageWiki has no analogous third-party consumer today. The underlying pattern (bearer-token-gated JSON API reusing the same aggregation function behind the HTML view) isn't novel for a FastAPI app anyway — that's just how FastAPI route handlers normally work. |
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

## Real test execution — why it's deferred, not just another scanner

v1's test runner is genuinely more than "detect whether tests exist": it clones each module,
runs `composer install --no-scripts --no-plugins` (scripts/plugins disabled specifically so a
malicious `composer.json` can't execute arbitrary code during install), then runs
`vendor/bin/phpunit --log-junit=...`, each step under a hard timeout and memory cap, in a
throwaway temp directory that's always cleaned up. Modules pinned below PHP 8.4 are retried
against a secondary sidecar container running an older PHP interpreter. All of this is real and
it works in production — but the isolation is intentionally minimal (ephemeral dir + timeouts,
not a container/VM/seccomp boundary around the test run itself), and even v1's own result capture
is thinner than its docs suggest: only overall `status` + a tail-truncated, secret-redacted output
blob is persisted — no per-test failure names or durations, even though the JUnit parse computes
them and then discards them.

**Why this isn't just folded into Phase 12**: Phase 12's scanners (PHPStan, PHPMD, phpcs,
PhpMetrics, Rector) only ever *read and analyze* PHP source — same risk class as today's
tree-sitter-php parsing. Actually running `composer install` + `phpunit` *executes* the scanned
module's code and its dependencies' code. That's a materially different, higher-risk capability
that MageWiki has never needed before (CLAUDE.md's "scanned code is never modified" principle
never had to answer "is scanned code ever *run*?"). If this is wanted eventually, it deserves its
own explicit phase with a deliberately-designed sandbox (e.g. a disposable per-run container with
no network access, rather than v1's timeout-and-temp-dir approach) — not a drive-by addition
riding on Phase 12's PHP-toolchain work.

## Operational lessons worth carrying over

A few non-feature, infrastructure-level lessons from v1's production history are worth applying
proactively rather than rediscovering the hard way:

- **One shared TTL cache, not one per scanner.** v1's `SqliteCache` is a single class/table
  (package-keyed, 24h TTL, upsert-on-write) reused by every external-API-backed check (Packagist
  metadata, security advisories, GitHub release lookups) via different cache keys — confirms the
  Phase 10 design above is right to share one cache table across the CVE and abandoned/outdated
  checks rather than building one per scanner.
- **Age-based retention pruning, excluding whatever a "latest" pointer still needs.** v1 grew an
  insert-only history table unbounded (a real production incident: SQLite file went from 3.7GB to
  822MB after a manual cleanup) until a daily pruning job was added — one that deletes rows older
  than N days *except* whichever row a denormalized "current state" column still points to. Once
  Phase 9/10 start accumulating per-scan history in Postgres, add the equivalent job up front
  rather than waiting for the same bloat to happen here.
- **Run subprocess-based scanners under a real init process.** v1 hit ~7000 zombie processes on
  staging because `php -S` as PID 1 never reaps children, and timed-out/crashed scanner
  subprocesses (PHPStan, Rector, phpcs) piled up — fixed with `tini`. Directly relevant to Phase
  12, which introduces the first subprocess-spawning scanners MageWiki will have; make sure
  whatever runs them (container entrypoint) reaps children properly from the start.
- **MageWiki's locking is already sound here.** v1 shipped two real concurrency bugs in
  production — a cron lock that silently failed to lock (the file handle was GC'd too early) and
  a non-atomic "check then add column" migration race — both now fixed. CLAUDE.md's existing
  design (a Postgres advisory lock for the whole scan, per the "Scan, cron, and cost control"
  section) already avoids the first bug class by construction; no action needed, just confirms the
  existing design choice was the right one.

## New phases to append to CLAUDE.md's phase plan

| Phase | Goal | Done when | Status |
|---|---|---|---|
| 9 | Parser-only quality checks (composer completeness, README presence, `@deprecated`, hardcoded secrets, test presence) + badge/KPI-ring UI foundation | New checks show up as badges on the module list and a stats page with KPI rings | Done |
| 10 | Dependency intelligence: CVE/security-advisory check + abandoned/outdated check | A module with a known-vulnerable dependency shows a blocking CVE badge citing the advisory | Done |
| 11 | Multi-repo fleet view | A repos-list page aggregates health across every repo MageWiki has scanned | Done |
| 12 | PHP static-analysis toolchain (PHPStan/PHPMD/phpcs/Rector/PhpMetrics) | Equivalent scanners run against a module and their findings show up as badges | Done — see CLAUDE.md's Phase 12 decision note. PhpMetrics from the original 5-tool list was dropped during scoping at first, then added back in a later session once asked directly what was still missing from this list — see CLAUDE.md's "PhpMetrics added" decision note |
| 12b | Magento upgrade readiness (PHP-version and magento/\* dependency compatibility against the latest Magento release, refreshed via a dedicated cron) | A module whose composer.json can't support the latest Magento release shows a blocking badge citing exactly why | Done — see CLAUDE.md's Phase 12b decision note; this is v1's actual headline feature, built against Magento's public GitHub repo rather than Packagist (Magento's own packages aren't on public Packagist at all) |
| 13 | One cloud (GCP or Azure) via Terraform, managed Postgres + pgvector *(renumbered from Phase 9 — still deferred, no cloud account/funds)* | Public demo deployment | Deferred |
