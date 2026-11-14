# MageWiki-AI — project rules for Claude Code

This file is the single source of truth for architecture decisions, data model, RAG design, phase plan, and working method. It is a transcription of the project's planning document (2026-11-04). Established decisions below are **settled and should not be changed without explicit justification** discussed with the user first.

The detailed, dated history of *how* each decision was reached — incident write-ups, bug fixes, and narrower per-feature rationale — lives in the `project-decision-log` skill (`.claude/skills/project-decision-log/SKILL.md`), loaded on demand rather than every session. This file keeps only the settled, always-relevant rules.

## Goal and scope

MageWiki-AI is a universal catalog of Magento 2 modules with an AI agent: it scans code, analyzes it with an LLM, stores the knowledge in a database, and lets PMs and developers ask natural-language questions (e.g. "do we have a module with a Klaviyo integration?"). This is a portfolio project on GitHub (`michalper/magewiki`) — it must ship as **finished**, not sprawling.

- **Universal**: works on any Magento 2.3/2.4+ store, no hardcoded paths. Sources: `app/code`,
  `vendor`, Composer `"path"`-type repositories declared in the root `composer.json` (e.g.
  in-house/monorepo-style modules outside both of the above), and `app/etc/config.php`
  (enabled/disabled status).
- **Read-only**: scanned code is never modified; no README files are ever written into scanned modules.
- **Knowledge lives in the database**: each module's description is a JSON record; Markdown is rendered on demand. Optional `.md` export is allowed and always writes outside the scanned project.
- **The agent answers only from collected data**, citing module and file; no results means "not found."
- **Version 1.0** = Phases 0–5: scanner, hash+diff, AI analysis with cache and budget, DB with vectors, agent with citations, chat UI and module page. Later: cron/webhook, BYOK in the UI, Ollama, dependency graph, plugin-conflict detection, evaluation.

## Architecture and stack (settled)

One Python backend, one Postgres database with extensions, one `docker compose up`.

| Layer | Technology | Role / decision |
|---|---|---|
| Backend API | Python, FastAPI, async SQLAlchemy, Alembic | Single backend, no Node.js server-side; webhooks use HMAC |
| Parsing | tree-sitter-php, lxml | PHP via tree-sitter (Python's `ast` module only reads Python); XML: di, events, webapi, crontab, db_schema |
| Database & vectors | PostgreSQL + pgvector (HNSW), tsvector, pg_trgm | Relational data, text, and vectors in one DB; no separate Qdrant/Milvus |
| Queue & cron | ARQ + Redis | Natively async; not Celery |
| LLM | LiteLLM, default DeepSeek, optional Ollama | BYOK; no LangChain in the core — the agent loop is a few dozen lines |
| Embeddings | OpenAI `text-embedding-3-small` or local `bge-m3` | Configured separately from the LLM (DeepSeek has no embeddings API) |
| Frontend | React via Next.js (App Router), TypeScript, Tailwind, shadcn/ui, TanStack Query | Chat via SSE (`fetch` + `ReadableStream`), not WebSocket; types generated with `openapi-typescript` |
| Deployment | Docker Compose | Scanned code is mounted `:ro` |

Don't mix model roles: Claude Code is the tool used to *write* the application; in production the application itself uses DeepSeek (cost) or a BYOK model.

## Scan, cron, and cost control

Re-analysis by AI runs only for files whose hash changed — a scan with no changes costs 0 tokens.

- **SHA256 hash per file**, diff per file (added/changed/removed). Removed files delete their chunks so chat doesn't hallucinate classes that no longer exist.
- **Module state machine**: `pending → scanning → analyzing → embedding → up_to_date`, plus `failed` (with `retry_count` and `last_error`) and `paused_budget`. A module is up to date when `analyzed_hash = current_hash`; after a crash, the worker knows what to resume.
- **Flow**: cron or webhook → `scan_repository` → diff → queue → `analyze_file` → `synthesize_module` (map-reduce over file summaries) → `embed_chunks`.
- **Idempotency**: `job_id = analyze:{file}:{hash}`, plus a Postgres advisory lock for the whole scan — two overlapping scans never duplicate work.
- **Cache**: `analysis_cache` table keyed by `(content_hash, model, prompt_version)`; changing the prompt invalidates the cache, and reverting a file costs nothing.
- **Budget**: `LLM_MONTHLY_BUDGET_USD` is checked before every LLM call; once exceeded, jobs move to `paused_budget`.
  This check (`is_budget_exceeded`) is a plain read with no locking — a soft, not a hard, limit: with several
  ARQ jobs running concurrently, each can read "under budget" before any of them commits its own cost, so real
  spend can briefly overshoot by roughly (concurrent jobs × per-call cost) before the next check catches it and
  moves things to `paused_budget`. Flagged by a full-repo code review ahead of the public release and accepted
  as-is rather than built out into real reservation accounting — a bigger architectural change than this
  single-user, budget-capped-at-$20/month tool currently needs.
- **Cron and webhook**: a nightly differential scan (e.g. `0 3 * * *`) is the safety net; a webhook from CI/CD (HMAC-signed, stable `_job_id` as debounce) gives speed. Both call the same `scan_repository` function.

## AI analysis and the README-in-the-database model

The AI returns structured JSON stored in the `module_docs` table (`jsonb` column); the README is only a view rendered from a template. Facts come from parsers; only interpretation comes from AI.

| JSON field | Content |
|---|---|
| `summary`, `description` | What the module does, business and technical |
| `features` | List of features, each with a `source` file reference; a feature without a source is rejected by validation |
| `integrations` | External systems (Klaviyo, InPost, ERP) |
| `tags` | From a controlled vocabulary; new tags wait for approval |
| `config_options`, `risks`, `confidence` | Keys from `system.xml`, risks, description confidence |
| `pm` / `dev` sections | Two text variants: without class names, and with classes/hooks/config |

Anti-hallucination rules:

- Lists of events, plugins, crons, endpoints, tables, and dependencies are inserted by parser code; the AI never invents them.
- `unknown` is allowed instead of guessing; code takes precedence over a module's own README.
- Tags carry `source` (`parser` or `ai`) and `confidence`. Deterministic signals (`composer.json`, a dependency on `Magento_Payment`, interfaces, `config.xml`) reinforce AI-assigned tags.
- Tag vocabulary (`app/analyzer/tags.py`'s `ALLOWED_TAGS`): `payments`, `shipping`, `marketing`, `erp`, `search`, `seo`, `checkout`, `admin-tools`, `performance`, `b2b`, `inventory`, `catalog`, `customer`, `cms`, `graphql`, `api`, `analytics`, `security`, `multi-store`, `theme`, `pwa`, `cron`. Expanded 2026-11-07 from the original 10 (the "starter" set) — flagged by a user looking at a real module's page and noticing categories like inventory/catalog/customer/cms/graphql/api had no tag that actually fit across a real 760-module fleet.
- README is stored together with `content_hash`, `model`, and `prompt_version`, so staleness is always knowable.

## RAG and the agent

Agentic RAG over hybrid search in Postgres: an agent with tools (tool calling via LiteLLM) answers only from data in the database and cites sources.

**Hybrid retriever** combines three signals via RRF (Reciprocal Rank Fusion, k=60):

| Signal | Technology | Catches |
|---|---|---|
| Semantic | pgvector + HNSW | Intent: "email marketing", "parcel lockers" |
| Keyword | `tsvector` | Class names, config keys, `klaviyo.com` |
| Identifiers | `pg_trgm` | `Vendor_Module`, typos, name fragments |

**Multi-level index**: module README (top level) → per-file summaries → code fragments (methods, XML blocks) for citation only. Chunking follows code structure, not character count. Source code for citations lives in the database; `read_file` reads from the database, not disk.

**Agent tools**: `search_modules`, `get_module`, `get_dependencies`, `get_module_findings`, `find_similar_modules`, `get_module_history`, `get_module_dependency_graph`, `find_duplicate_module_pairs`, `find_by_event`, `find_by_class`, `read_file(path, lines)`, `list_modules`.

**Question routing**:

| Question type | Tool |
|---|---|
| "Do we have a Klaviyo integration?", "how does the module send data?" | Hybrid search + module card + `read_file` |
| "Show all payment modules", "how many…" | `list_modules` (SQL over tags/integrations/status) with total count and pagination |
| "Who listens to this event?", "who overrides this class?" | `find_by_event`, `find_by_class` (SQL) |
| "Do we have two modules doing the same integration?" | `find_similar_modules` (embedding cosine similarity) |
| "What changed in this module recently?", "is this module getting better or worse?" | `get_module_history` (SQL over `module_history_snapshots`) |
| "Why does this module have finding X?", "what quality issues does this module have?" | `get_module_findings` (SQL over `module_quality_findings`, with real file/line citations) |
| "What does this module depend on, transitively?", "show the dependency graph" | `get_module_dependency_graph` (BFS over module.xml/di.xml relations) |
| "Which modules across the fleet look like duplicates?" | `find_duplicate_module_pairs` (fleet-wide embedding cosine similarity, distinct from the per-module `find_similar_modules`) |

Enumeration questions go through SQL, because top-k retrieval doesn't guarantee completeness by nature.

**Response**: SSE stream with `sources`, `token`, `done` (token usage) events. `audience` modes: `pm` (business language, no class names) and `dev` (classes, paths, events). The response includes the last scan date and module status (enabled vs. on-disk only).

System prompt enforces: answer only from tool results, every claim cited, no results means "not found."

Explicitly **not** chosen: pure vector RAG, GraphRAG, a separate vector database, LangChain as the core. Post-1.0 wishlist is now fully closed: the retrieval-debugging panel, reranking, and query rewriting (Phase 17) are all done — see the `project-decision-log` skill for each one's design.

## Test data

Always **public code** (e.g. a local clone of `magento/magento2`, or other publicly available modules), **never confidential client code**. The repo is public from day one — no secrets and no NDA-covered client code ever enter the commit history.

The `Ordo_Automation` module (at `/Users/michalper/Projects/magento-ordo-test/vendor-src-sync` on the author's machine) is the author's own **public product**, not confidential client code — it is allowed as scanner test/fixture data from Phase 1 onward (referenced by path/env var, not copied into this repo).

## Phase plan

MVP = Phases 0–5. Each phase is done separately: first a plan for approval, then code with tests, then a small commit. Don't skip phases.

| Phase | Goal | Done when |
|---|---|---|
| 0 | Repo skeleton, docker-compose, migrations, `.env.example` | `docker compose up` starts the database, API, and web |
| 1 | Scanner without AI: module discovery, XML/composer/PHP parsers, saved to the DB | Dashboard shows the module list from a demo scan |
| 2 | Per-file hash, diff, module states | A second scan with no changes creates 0 tasks |
| 3 | AI analysis: JSON schema, tag dictionary, cache, cost tracking, budget, README rendered from the DB | Module descriptions and cost are visible in the DB |
| 4 | Embeddings and hybrid retriever (vector + FTS + trigram, RRF) | A query returns the right files |
| 5 | Agent with tools, SSE chat, citations, pm/dev modes | Clickable sources in the UI |
| 6 | Cron, HMAC webhook, BYOK, Ollama, dependency graph | Nightly scan runs unattended |
| 7 | Evaluation suite (recall@k, MRR, negative/enumeration questions), README, GIF | Results in the README, vector vs. FTS vs. hybrid chart |
| 7b | CI/CD: GitHub Actions (lint, tests, Docker build, RAG eval on PR) | recall@k posted as a PR comment |
| 8 | Kubernetes: Helm or Kustomize, scan CronJob, tested on `kind` | Full stack runs on a local cluster |
| 9 | Parser-only quality checks (composer completeness, README presence, `@deprecated`, hardcoded secrets, test presence) + badge/KPI-ring UI foundation | New checks show up as badges on the module list and a stats page with KPI rings |
| 10 | Dependency intelligence: CVE/security-advisory check + abandoned/outdated check | A module with a known-vulnerable dependency shows a blocking CVE badge citing the advisory |
| 11 | Multi-repo fleet view | A repos-list page aggregates health across every repo MageWiki has scanned |
| 12 | PHP static-analysis toolchain (PHPStan/PHPMD/phpcs/Rector) | Equivalent scanners run against a module and their findings show up as badges |
| 12b | Magento upgrade readiness (PHP-version and magento/\* dependency compatibility against the latest Magento release) | A module whose composer.json can't support the latest Magento release shows a blocking badge citing exactly why |
| 13 | Public demo deployment — Fly.io (api + web) + Neon (managed Postgres with pgvector), not the originally planned GCP/Azure-via-Terraform (no budget for that; see the decision log for why Neon over Fly's own Postgres) | A real, live, publicly reachable deployment |
| 14 | Deeper structural facts: `webapi.xml` (REST/SOAP endpoints), `crontab.xml` (scheduled jobs), `db_schema.xml` (tables/columns), `system.xml` (admin config options) — same pattern as the "Scanner coverage: .phtml templates and GraphQL schemas" decision above (structured facts, not LLM-guessed), one new parser + table + prompt wiring per file type | Each shows up as its own structured fact block in the synthesis prompt and a `features[].source` a module's AI-written description can cite, the same way GraphQL fields already do |
| 15 | Cross-module conflict detection, round 2: `di.xml` `<preference>` conflicts (two modules declaring a different preference for the same interface — classic silent-override Magento bug), `crontab.xml` job-code conflicts, `graphql_fields` conflicts — same fleet-wide Phase-C pattern and `module_quality_findings` table as the existing plugin/composer/webapi/db_schema/circular-dependency conflict checks; data already parsed (Phase 1 `di_preferences`, Phase 14 `cron_jobs`/`graphql_fields`), so this is new detection logic only, no new scanning risk | Each new check_type shows up as a badge the same way `plugin_conflict`/`webapi_route_conflict`/etc. already do, folded into the "Cross-module conflicts" Stats tile |
| 16 | Module history: a lightweight per-scan history table + a "what changed" view (new CVEs, upgrade-readiness regressions, finding-count deltas since the last scan or over a chosen window) | A module/repo page can answer "what got better or worse since last month," not just "what's true right now" |
| 17 | RAG query rewriting, opt-in (mirrors how reranking shipped: a second LLM call, `QUERY_REWRITE_ENABLED` default `false`, budget-gated via the same `analysis_cache`/Prometheus ledger) — the one item CLAUDE.md's own RAG section already named as deferred pending this exact cost decision | Vague/colloquial chat questions retrieve noticeably better without changing the underlying hybrid retriever |
| 18 | Alerting: a plain webhook POST (`ALERT_WEBHOOK_URL`, empty disables it) fired once per `scan_repository` run when an alert-worthy check_type's finding count (`ALERT_CHECK_TYPES`, default `hardcoded_secret,security_advisory`) goes up for any module since its last scan — reuses Phase 16's `write_history_snapshots()` before/after `finding_counts` comparison, no new query; one summary call per scan, not per module, to avoid spamming whatever it's pointed at. Zero new infrastructure (no SMTP, no Slack SDK) — the payload's top-level `text` field works directly with a bare Slack Incoming Webhook or Google Chat webhook URL | A new secret or CVE on any scanned module fires exactly one webhook POST; a routine rescan with nothing alert-worthy fires none |
| 19 | Cross-module conflict detection, round 3: `acl.xml` admin-ACL facts — a new `acl_resources` table via a new parser, same pattern as Phase 14's structural-fact tables — feeding two checks: a missing-ACL check (an admin route/menu item declared without a bound ACL resource, so any logged-in admin can reach it) and a duplicate-ACL-resource-id conflict (two modules declaring the same resource id; Magento's declarative-config merge lets one silently win, same risk class as the existing `preference_conflict`/`db_schema_conflict` family) | A module with an unprotected admin route or a clashing ACL resource id shows a badge citing the exact file, folded into the "Cross-module conflicts" Stats tile |
| 20 | Cross-module conflict detection, round 4: `indexer.xml`/`mview.xml` facts (new `module_indexers` table, same parser pattern) and an indexer/mview-id conflict check — two modules declaring the same `indexer_id` or `view_id` hit the same declarative-merge silent-override risk as `di.xml` preferences and `db_schema.xml` columns | Each new check_type shows up as a badge the same way `preference_conflict`/`db_schema_conflict` already do, folded into the same Stats tile |
| 21 | Semantic duplicate/overlap detection + a module comparison page: reuses Phase 4's existing module-level embeddings (no new scan, no new external call) to surface pairs of modules above a cosine-similarity threshold that aren't the same vendor/package as likely redundant integrations, plus a side-by-side A/B compare view (tags, integrations, findings, dependencies) over data already in the DB | A module page shows its most-similar other modules, and picking two opens a compare view with no new scan or LLM call |
| 22 | Cross-module conflict detection, round 5: `etc/frontend/routes.xml`/`etc/adminhtml/routes.xml` facts (new `module_routes` table, same parser pattern) — two checks, `route_id_conflict` (ambiguous `getUrl()` reverse-route resolution) and `frontname_conflict` (ambiguous URL dispatch), both scoped per area since Magento's own uniqueness constraint is per-area, not global | A module with a clashing route id or frontName within the same area shows a badge citing the exact area/value, folded into the "Cross-module conflicts" Stats tile |
| 23 | Cross-module conflict detection, round 6: `view/{base,frontend,adminhtml}/widget.xml` facts (new `module_widgets` table, same parser pattern, no area column -- Magento merges widget ids into one global namespace regardless of which view dir declared them) — a `widget_id_conflict` check for two modules declaring the same widget id | A module with a clashing widget id shows a badge citing the exact id, folded into the "Cross-module conflicts" Stats tile |
| 24 | Lightweight access gate (shared `X-Access-Token` header, `WRITE_ACCESS_TOKEN` env var) on the endpoints that cost money or mutate shared global state — `POST /chat`, `PATCH /settings/llm`, `POST /scan[/stream]` — so an operator can safely enable a real LLM key on the public Fly.io demo later without anonymous visitors spending `LLM_MONTHLY_BUDGET_USD` or rewriting the shared `RuntimeLlmConfig` row; empty token (the default) leaves today's open local/self-hosted behavior unchanged. All read-only browsing (module list/detail, search, stats) stays open — see `docs/v1-port-roadmap.md`'s original note and the decision log for why this, not sessions/OAuth | A write/chat/scan call without the configured token gets 401; the catalog itself stays fully browsable with no token at all |
| 25 | Cross-module conflict detection, round 7: `etc/adminhtml/menu.xml` (admin menu item ids — a confirmed hard Magento error on duplicate, kept `warning` severity for family consistency per the `circular_dependency` precedent) and `etc/cache.xml` (cache type ids — a silent-merge-override risk only when two modules disagree on `instance`, same shape as `preference_conflict`); two new parsers/tables (`module_menu_items`, `module_cache_types`), same fleet-wide Phase-C pattern as every prior round | A module with a clashing menu item id or a disputed cache type instance shows a badge citing the exact id, folded into the "Cross-module conflicts" Stats tile |

Version 1.0 ships before Phases 7b–9: a finished project with six technologies beats an unfinished one with ten.

### Backlog: porting ideas from v1

The author previously built a PHP tool for his employer Cognize — the predecessor MageWiki-AI (the open-source Python rewrite) succeeds, referred to here only as "v1" since it's Cognize's property. Phases 9–12 above come from a curated review of what v1 does in production; the full inventory (what's ported, what's skipped as Cognize-internal, and the detailed CVE-check design) lives in `docs/v1-port-roadmap.md`. Nothing here is copied code — concepts only, per the "no client-confidential code" rule below.

## Working method

- Start each phase in plan mode; propose a plan and wait for approval before writing code.
- Require tests alongside code (fixture: a small module under `backend/tests/fixtures/`). Every new feature needs both 100% unit-test coverage (backend `pytest`/frontend `vitest`, enforced in CI via `codecov.yml`'s project+patch targets) and real Playwright e2e coverage of its user-visible behavior — not just one or the other.
- Reset context between phases.
- Record settled, always-relevant rule changes in this file. Record incident write-ups, bug fixes, and narrower per-feature decision rationale in the `project-decision-log` skill, as they're made.
- Repo language is English: README, docs, comments, commit messages, UI.
- The repo is public from day one: no secrets, no client-confidential code, ever, in commit history.

## License

MIT.
