# MageWiki-AI — project rules for Claude Code

This file is the single source of truth for architecture decisions, data model, RAG design, phase plan, and working method. It is a transcription of the project's planning document (2026-11-04). Established decisions below are **settled and should not be changed without explicit justification** discussed with the user first.

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

**Phase 3 deviation (recorded 2026-11-05):** Phase 3's AI analysis (`analyze_file` / `synthesize_module`) is implemented and verified against **Anthropic Claude** rather than DeepSeek, because real Anthropic API billing was available for genuine end-to-end verification this phase (model configured via `LLM_MODEL` in `.env`, default `anthropic/claude-haiku-5-5` — verify the exact LiteLLM model string empirically against the installed `litellm` package, the same discipline already used for `tree-sitter-php` and `arq`/`pytest-asyncio` in earlier phases). LiteLLM itself remains the abstraction layer — only the configured provider/model changed. DeepSeek and Ollama remain the stated production default per the `LLM` row above and stay wired as dormant BYOK options (`DEEPSEEK_API_KEY`, `OLLAMA_BASE_URL` in `.env.example`); switching back is a config change, not a code change.

Don't mix model roles: Claude Code is the tool used to *write* the application; in production the application itself uses DeepSeek (cost) or a BYOK model.

**Phase 8 decision (recorded 2026-11-06):** Kubernetes manifests use **Kustomize**, not Helm — `kubectl` has Kustomize built in (no extra tooling), and plain YAML + a `kustomization.yaml` fits a single-environment (`kind`) demo better than a chart's templating layer. See `k8s/`. The scan `CronJob` is additive to the app's own internal ARQ cron (`cron(nightly_scan_all, ...)` in `app/tasks/worker.py`, already running wherever the worker Deployment runs) — it demonstrates the k8s-native primitive by hitting `POST /scan` against the committed `tests/fixtures/demo-store` fixture, not a replacement for the in-process schedule.

## Scan, cron, and cost control

Re-analysis by AI runs only for files whose hash changed — a scan with no changes costs 0 tokens.

- **SHA256 hash per file**, diff per file (added/changed/removed). Removed files delete their chunks so chat doesn't hallucinate classes that no longer exist.
- **Module state machine**: `pending → scanning → analyzing → embedding → up_to_date`, plus `failed` (with `retry_count` and `last_error`) and `paused_budget`. A module is up to date when `analyzed_hash = current_hash`; after a crash, the worker knows what to resume.
- **Flow**: cron or webhook → `scan_repository` → diff → queue → `analyze_file` → `synthesize_module` (map-reduce over file summaries) → `embed_chunks`.
- **Idempotency**: `job_id = analyze:{file}:{hash}`, plus a Postgres advisory lock for the whole scan — two overlapping scans never duplicate work.
- **Cache**: `analysis_cache` table keyed by `(content_hash, model, prompt_version)`; changing the prompt invalidates the cache, and reverting a file costs nothing.
- **Budget**: `LLM_MONTHLY_BUDGET_USD` is checked before every LLM call; once exceeded, jobs move to `paused_budget`.
- **Cron and webhook**: a nightly differential scan (e.g. `0 3 * * *`) is the safety net; a webhook from CI/CD (HMAC-signed, stable `_job_id` as debounce) gives speed. Both call the same `scan_repository` function.

**Generic scan roots decision (recorded 2026-11-06):** `POST /scan`/`POST /webhooks/scan`
take a `path`, but a running container can never gain access to an arbitrary new host
path — Docker bind mounts are fixed at container-start time. Before this, the only
mount mechanism was `MAGEWIKI_ORDO_FIXTURE_PATH`/`MAGEWIKI_MAGENTO_FIXTURE_PATH`, two
fixture-specific mounts used by the real-fixture tests and the evaluation suite (naming
one *specific, known* repo each) — not a general "scan whatever repo I want"
mechanism, so adding any new repo meant hand-editing `docker-compose.yml`. Added
`MAGEWIKI_SCAN_ROOT_1/2/3` (same `host-path:host-path:ro` bind-mount convention,
mounted into `api`/`worker`/`php-analyzer`): numbered, not a comma-separated list,
because `docker-compose.yml`'s `volumes:` can't loop over a variable-length value.
Once an operator sets one scan root per top-level repo-storage location on a server,
every repo added under it is scannable immediately via the UI or webhook — no further
compose edits or restarts. `GET /scan-roots` reports what's currently configured, and
the Modules page shows it as helper text next to the Scan input, so the system is
self-documenting instead of requiring a read of `docker-compose.yml`. The two
fixture-specific vars are unchanged — they serve a different, narrower purpose
(tests/eval need one named repo, not "any repo under a general area") and keep working
exactly as before.

**Composer path-repository discovery (recorded 2026-11-06):** real-world gap, flagged
by a user testing against his employer's actual store: `find_modules()`
(`app/scanner/discovery.py`) only ever walked `app/code` and `vendor`, so a module
installed via a Composer `"path"`-type repository declared in the root `composer.json`
(`"repositories": {"local": {"type": "path", "url": "src/*/*"}}` — a common way to
install in-house/monorepo-style modules that live entirely outside both directories)
was silently invisible to a scan. Composer path repositories do typically get
symlinked into `vendor/` on install, which `os.walk()`'s default `followlinks=False`
wouldn't follow anyway (verified directly: a symlinked directory is listed in a
parent's `dirnames` but never visited as a `dirpath` itself) — relying on that symlink
existing would be fragile regardless (skippable via `"symlink": false`, absent before
`composer install` has ever run). `app/scanner/composer_repositories.py`'s new
`find_path_repository_globs()` reads the declaration directly instead (handling both
Composer's legacy array-of-objects and newer object-keyed-by-name `repositories`
shapes), and `find_modules()` globs each declared path against the repo root, tagging
matches with a new `source_type = "composer_path"` — the frontend already renders
`source_type` as plain text with dynamically-derived filter options, so no frontend
change was needed. Verified end-to-end against a real `POST /scan` (not just unit
tests): a `src/<vendor>/<package>/etc/module.xml` fixture matching `src/*/*` was
discovered and persisted with the correct `source_type`.

**Live scan progress decision (recorded 2026-11-06):** a real scan of a large store
(hundreds of modules, each incurring real HTTP calls to php-analyzer and
Packagist/GitHub) can take many minutes, and `POST /scan` was one blocking request —
the UI showed a static "Scanning..." button with zero feedback until it finished. The
real blocker wasn't the frontend: `scan_repository()` did all its work in one Postgres
transaction, committing once at the very end, so no other query (including a polling
`GET /modules`) could see any progress no matter how the UI was built — deliberate,
since the whole-scan mutual-exclusion lock (`pg_try_advisory_xact_lock`) was
transaction-scoped. Fixed by committing per module instead of once at the end (each
module's ARQ jobs are now enqueued right after its own commit too, so workers can start
on module 1 while module 500 is still scanning), which forced the lock off the
transaction's lifetime onto `pg_try_advisory_lock`/`pg_advisory_unlock`
(session-scoped, held for the whole scan regardless of how many commits happen inside
it, and auto-released by Postgres if the connection terminates uncleanly — verified
directly: killing the client mid-scan released the lock within one connection cycle).
`scan_repository()` became a thin wrapper around a new `scan_repository_events()`
generator so every existing non-streaming caller (cron, webhook, CLI, evaluation)
keeps working unchanged; a new `POST /scan/stream` (SSE, same pattern as `/chat`) feeds
the same generator's events to the Modules page as a progress bar plus a scrollable,
terminal-style log, and the frontend's SSE parsing got extracted to a shared
`lib/sse.ts` now that there are two real call sites. Verified end-to-end against a real
224-module checkout (`magento/magento2`): `GET /modules` genuinely filled in
progressively during the scan, not just at the end.

**Advisory-lock connection-pinning fix (recorded 2026-11-06):** the per-module-commit
design above introduced a real bug, caught by CI (no concurrent activity to blame,
unlike local dev where a live scan masked it at first as "resource contention"): a
session-level advisory lock is tied to one specific physical connection, but
`AsyncSession` checks out a *new* connection from the pool each time it begins a
transaction (autobegin after every `commit()`) — and the scan commits once per module,
by design. The lock was acquired through `session` on one connection and "released"
through `session` later on a different one: `pg_advisory_unlock` silently returned
`false` (not actually held by the caller), leaking the lock forever onto the original,
now-idle-in-the-pool connection. Fixed by acquiring the lock through a `Connection`
obtained directly from `app.db.engine` instead of through `session` — pinned to one
physical connection for its whole scope, unlike a `Session`, so acquire and release are
now guaranteed to happen on the same connection regardless of how many commits the
scan's own session churns through.

**LLM structured-output validation retry (recorded 2026-11-06):** forced tool-use
(Anthropic/OpenAI-style function calling) heavily biases a model toward the declared
JSON Schema but does not *guarantee* every required field is present — confirmed in
production at real scale (a 751-module store): `ModuleDoc`'s `pm_text`/`dev_text`/
`description` were occasionally omitted even though the schema marks them required,
and the resulting Pydantic `ValidationError` propagated straight out uncaught, failing
the whole module (`state=failed`) instead of retrying the way a malformed-JSON response
already did. `app/analyzer/client.py`'s `_call_tool_use`/`_call_plain_json` now both
validate each attempt (not just check it parses as JSON) and retry once with the
validation error appended to the prompt before giving up — same corrective-reprompt
shape already used for JSON-parse failures, just extended to schema validation too.
Verified against the real, previously-failing production case (not just mocks):
manually re-triggered synthesis for a module that had failed with exactly this error,
confirmed it now persists a complete, real `ModuleDoc`.

**Enabled-status filter (recorded 2026-11-06):** real-world noise, flagged by a user
testing against a real 751-module store: Magento's own internal dev/test scaffolding
(`Magento_TestModule*`, `Magento_TestSetupDeclarationModule*` — some with real
`magento/module-*-test` composer packages) gets discovered under `vendor/` just like
any real module and clutters the list. `Module.enabled` already distinguishes this
case — it's `None` specifically when a module isn't listed in `app/etc/config.php`'s
`modules` array at all (as opposed to `False`, present with an explicit `0`) — but the
Modules page had no way to filter by it, only by `source_type`/`state`. Added an
`enabledFilter` dropdown (`frontend/app/modules/page.tsx`) with the same three-state
vocabulary as the existing `EnabledBadge` (enabled/disabled/unknown). Deliberately not
a hardcoded "Magento test module" name pattern — filtering on `enabled` is the more
"universal" fix and generalizes to any vendor's unregistered dev/test scaffolding, not
just Magento's own. Opt-in, not a default hide: auditing everything physically in
`vendor/` (e.g. the Phase 10 CVE check) still has legitimate uses a product module list
alone doesn't serve. Verified end-to-end against the real store: "Unknown" narrowed 751
modules to exactly the 53 that included every `Magento_TestModule*`/`Magento_A`/
`Magento_B`-style fixture; "Enabled" showed the complementary 698.

**Multi-store directory scan + cross-store overlap (recorded 2026-11-06):** real-world
request — on a real server, many stores commonly live side by side under one parent
directory (e.g. `/sites/store-a`, `/sites/store-b`, ...), and scanning N stores meant N
separate manual `POST /scan` calls. The data model already supported this with zero
schema change: `Module`'s unique constraint is `(repo_root, name)`, not `(name)` alone,
so the same module name already coexists as separate rows across different `repo_root`
values; `current_hash` is computed purely from path-relative-to-module-root + file
bytes (`repo_root` never enters the hash), so two installs of the literally same
version naturally hash identically. New `app/scanner/multi_store.py`'s
`find_store_roots()` reuses `find_modules()`'s own "looks like a store/module root"
signals to expand a container directory into its store-shaped children; new
`scan_paths_events()`/`scan_paths()` (`app/scanner/orchestrator.py`) wrap
`scan_repository_events()` — delegating straight through unchanged whenever `path`
resolves to 0-1 roots (every existing single-store call site, including cron/webhook/
CLI/evaluation, is untouched since only the interactive `POST /scan`/`POST
/scan/stream` routes call the new functions), looping sequentially over multiple roots
otherwise (the existing per-root advisory lock already makes this safe — no new
locking needed). New `GET /modules/overlap` groups `Module` rows by name across
repo_roots and flags `version_drift` when `current_hash` isn't identical across a
group — directly answers "how many modules repeat across stores, and are they the same
version." Verified end-to-end against real production data (not just the synthetic
fixture): scanning a container with 2 store-shaped children correctly produced
`stores_scanned: 2`, and `GET /modules/overlap` against the real DB (containing two
real, previously-scanned stores) correctly surfaced 6 genuinely shared Magento core
modules with real version drift between them, plus the synthetic fixture's identical
module correctly flagged `version_drift: false`.

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
- Starter tag vocabulary: `payments`, `shipping`, `marketing`, `erp`, `search`, `seo`, `checkout`, `admin-tools`, `performance`, `b2b`.
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

**Agent tools**: `search_modules`, `get_module`, `get_dependencies`, `find_by_event`, `find_by_class`, `read_file(path, lines)`, `list_modules`.

**Question routing**:

| Question type | Tool |
|---|---|
| "Do we have a Klaviyo integration?", "how does the module send data?" | Hybrid search + module card + `read_file` |
| "Show all payment modules", "how many…" | `list_modules` (SQL over tags/integrations/status) with total count and pagination |
| "Who listens to this event?", "who overrides this class?" | `find_by_event`, `find_by_class` (SQL) |

Enumeration questions go through SQL, because top-k retrieval doesn't guarantee completeness by nature.

**Response**: SSE stream with `sources`, `token`, `done` (token usage) events. `audience` modes: `pm` (business language, no class names) and `dev` (classes, paths, events). The response includes the last scan date and module status (enabled vs. on-disk only).

System prompt enforces: answer only from tool results, every claim cited, no results means "not found."

Explicitly **not** chosen: pure vector RAG, GraphRAG, a separate vector database, LangChain as the core. Post-1.0: reranking, query rewriting, a retrieval-debugging panel in the UI.

**Configurable embedding dimension (recorded 2026-11-06):** real bug, found while
actually running the Phase 7 eval suite against Ollama's `bge-m3` after hitting an
OpenAI "no credits remaining" error mid-run: `chunks.embedding` was hardcoded
`Vector(1536)` (OpenAI `text-embedding-3-small`'s dimension) with an HNSW index built
on that fixed dimension — despite this file's own BYOK row promising `bge-m3` (1024-dim)
as a local embedding option. Inserting a `bge-m3` embedding failed outright
(`expected 1536 dimensions, not 1024`). Worse: the runtime BYOK override
(`RuntimeLlmConfig.embedding_model`, settable live via `/settings` with zero redeploy)
had **no guard at all** — any operator picking a non-1536-dim model via the Settings UI
would hit the identical crash later, inside an unrelated scan's embed step. New
`EMBEDDING_DIMENSIONS` setting (`.env`, default `1536`) plus migration `0013` resize
`chunks.embedding`/its HNSW index to match — the migration refuses (raises, doesn't
silently truncate) if `chunks` already has rows in a different dimension, since
switching embedding models never had a safe automatic data-migration path anyway
(different models produce incomparable vector spaces). `PATCH /settings/llm` now probes
a changed `embedding_model`'s *real* output dimension with one tiny live call
(`embed_text`, not a hardcoded model→dimension lookup table that would go stale) and
rejects a mismatch with a 400 before saving, instead of only failing later. **Still
explicitly not solved**: no column tracks which model produced an existing chunk's
embedding, and there's no automatic re-embed-everything workflow when the model
changes — confirmed via research that this gap already existed before this fix (model
switching has always silently left old embeddings in a stale vector space); closing it
is materially bigger scope than what was needed to unblock the eval and is deferred,
not forgotten.

## Test data

Always **public code** (e.g. a local clone of `magento/magento2`, or other publicly available modules), **never confidential client code**. The repo is public from day one — no secrets and no NDA-covered client code ever enter the commit history.

The `Ordo_Automation` module (at `/Users/michalper/Projects/magento-ordo-test/vendor-src-sync` on the author's machine) is the author's own **public product**, not confidential client code — it is allowed as scanner test/fixture data from Phase 1 onward (referenced by path/env var, not copied into this repo).

**Test infrastructure must never share live state with the dev containers (recorded
2026-11-06):** `tests/conftest.py` already redirected `DATABASE_URL` to an isolated
`magewiki_test` database (dropped/recreated fresh every pytest session) after a real
external user's running webapp broke from pytest sharing his dev DB — but Redis was
never given the same treatment, and it caused a genuinely long-lived flake:
`test_queue_integration.py`'s `queued_jobs()` assertions raced against the actual
`worker` container, which is always running in dev and actively consumes from the
same `redis://.../0` ARQ queue tests enqueue into — real job IDs from a live user scan
(e.g. `analyze:664:...`, later `analyze:857:...`, `analyze:977:...`) showed up in
failure output repeatedly across this session, misdiagnosed more than once as
"resource contention" before the actual shared-Redis root cause was confirmed. Fixed
the same way as the database: `conftest.py` now also redirects `REDIS_URL` to logical
database index 15 (Redis supports 16 independent logical DBs on one server at zero
extra infrastructure cost) before any `app.*` import, flushed fresh once per pytest
session alongside the DB drop/recreate. Verified: the two previously-flaky tests
passed 3/3 consecutive runs after the fix, and the full suite went from an
intermittent 1-2 failures to 203/203 passing.

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
| 13 | One cloud (GCP or Azure) via Terraform, managed Postgres + pgvector | Public demo deployment |

Version 1.0 ships before Phases 7b–9: a finished project with six technologies beats an unfinished one with ten.

**Phase 9 decision (recorded 2026-11-06):** a single generic `module_quality_findings` table
(`check_type`, `severity`, `file_path`, `line`, `message`) backs every parser-only quality check,
rather than one table per check. v1 hit exactly this gap — it shipped per-scanner columns first
and had to do a late, painful migration to a generic `module_scans`/`issues_json` table once more
scanners arrived — so MageWiki built the generic shape from the start, reused unchanged by Phases
10 and 12 below.

**Phase 10 decision (recorded 2026-11-06):** `app/scanner/semver.py` is a from-scratch Composer-
constraint interval-overlap checker — no installed Python library matches Composer's constraint
grammar closely enough to trust for the CVE check. Verified against live Packagist data, not just
mocks, which caught two real response-shape bugs: `advisories` is `[]` (not `{}`) when a package
has none, and `affectedVersions` uses a single `|` as its OR separator, not `||`.

**Phase 11 decision (recorded 2026-11-06):** no schema change — `Module.repo_root` already let
multiple repos coexist in one DB, so `GET /repos` is purely a read-only aggregation over existing
data, not a new multi-tenancy/"client" concept.

**Phase 12 decision (recorded 2026-11-06):** a new `php-analyzer` sidecar (plain PHP, no
framework, `php:8.3-cli-alpine`, reachable only over the internal docker network) runs the real
PHP tooling the Python-only backend never could. **Scope note: only 4 of the originally-listed 5
tools were actually built — PhpMetrics was dropped during scoping** (the roadmap table above now
reflects this; no replacement or follow-up is scheduled for it). All four new check types
(`phpstan_error`, `phpmd_issue`, `phpcs_violation`, `php_compat_issue`) default to severity
`"warning"` — informational, not blocking, since there's no "upgrade readiness" gate concept yet
to make a PHP-compat finding a hard blocker the way v1 treats it. Explicit user decision: accept
full-rescan-every-time for now rather than building a hash-skip-if-unchanged optimization, since
nothing today is large enough to prove that's actually needed. Also worth flagging: `ModuleSummary`
now carries 10 flat per-check-type count fields (3 added in Phase 9, 3 more in Phase 10, 4 more
here) — a generic `dict[check_type, count]` would scale better, but wasn't worth refactoring three
times' worth of already-shipped, working frontend code for a cleanliness win nobody asked for.
Worth doing if an even 5th wave of check types ever shows up.

**Phase 12b decision (recorded 2026-11-06):** this is v1's actual headline feature ("upgrade
readiness"), deliberately left out of Phase 12 and called out there as "no 'upgrade readiness'
gate concept yet." Live-tested during planning: Magento's own packages
(`magento/framework`, every `magento/module-*`, `magento/product-community-edition`) **do not
exist on public Packagist** — confirmed via a direct request, 404 — they're distributed only
through Magento's private, auth-gated `repo.magento.com` Composer repository. That means Phase
10's existing Packagist-based checks have never actually been able to evaluate real Magento
package compatibility, only third-party libraries. The data instead comes from Magento's public
GitHub repo (`github.com/magento/magento2`), which exposes `composer.json` at every release tag
with no authentication needed — Marketplace auth is only required to *install* packages, not to
read metadata from the public source mirror; this is the same data source v1 itself used. A
second real bug found via live verification (not mocks): the monorepo's own `composer.lock` never
lists `magento/framework` or any `magento/module-*` package in its `packages` array — those
components are `replace`d by the project itself (self-satisfied from the git checkout, not
resolved from Packagist), so the exact per-component version actually comes from `composer.json`'s
`replace` map, not `composer.lock` at all (`app/scanner/magento_github.py`). Two new blocking
check types, `magento_php_incompatible` and `magento_version_blocker`, reuse the generic
`module_quality_findings` table and `semver.py`'s `constraints_overlap()` — no new detection
machinery. Per the user's request for a cyclical check (not just on manual scan), a new
independent cron `refresh_magento_release_cache` (`app/tasks/worker.py`) pre-warms the cached
"latest release" data daily; the existing `nightly_scan_all` cron then naturally picks up a new
Magento release on its next run, since it already recomputes every quality finding from scratch —
no separate recompute path was needed. Also worth flagging: GitHub's `/releases/latest` is
documented to exclude prereleases, but at verification time it resolved to `2.4.10-alpha1`
(`minimum-stability: alpha` in Magento's own composer.json) — Magento evidently doesn't mark its
newest tag as a GitHub "prerelease" even though its own stability flag says alpha. Not treated as
a bug to fix now (this is exactly what "the latest tagged release in the public repo" means today);
worth revisiting with an explicit stable-tag filter if it turns out to matter in practice.

### Backlog: porting ideas from v1

The author previously built a PHP tool for his employer Cognize — the predecessor MageWiki-AI (the open-source Python rewrite) succeeds, referred to here only as "v1" since it's Cognize's property. Phases 9–12 above come from a curated review of what v1 does in production; the full inventory (what's ported, what's skipped as Cognize-internal, and the detailed CVE-check design) lives in `docs/v1-port-roadmap.md`. Nothing here is copied code — concepts only, per the "no client-confidential code" rule below.

## Working method

- Start each phase in plan mode; propose a plan and wait for approval before writing code.
- Require tests alongside code (fixture: a small module under `backend/tests/fixtures/`).
- Reset context between phases.
- Record new decisions in this file as they're made.
- Repo language is English: README, docs, comments, commit messages, UI.
- The repo is public from day one: no secrets, no client-confidential code, ever, in commit history.

## License

MIT.
