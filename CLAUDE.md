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

**Auto-migration on startup (recorded 2026-11-07):** real production incident — a
teammate pulled a new version, and `api` crashed every `/modules` request with
`sqlalchemy.exc.ProgrammingError: column modules.homepage does not exist` (the
`composer.json` facts migration had never been applied to his DB), surfaced to the
frontend only as a generic "Failed to load modules." `docker-compose.yml` never ran
migrations itself — the README documented `docker compose exec api alembic upgrade
head` as a required manual step, easy to forget on every pull. Fixed with a dedicated
one-shot `migrate` service (`alembic upgrade head`, then exits) that `api`/`worker`
both `depends_on` with `condition: service_completed_successfully` — not api/worker
running it themselves, which would race the two against each other. Verified against
a real `docker compose up`: `migrate` starts only after `db`/`redis` are healthy, exits
0, and only then do `api`/`worker` start; `/modules` serves real data (including the
previously-missing `homepage` column) immediately. This already matched the
Kubernetes manifests' own pattern (Phase 8's "one-shot migration `Job`") — docker-
compose was the one place still requiring a manual step. CI's `e2e-smoke` job dropped
its own now-redundant manual `alembic upgrade head` step for the same reason.

Two follow-ups, same session, same spirit (user: "co jeszcze można poprawić żeby było
lepiej zautomatyzowane i łatwiejsze?"): (1) `GET /health` (`app/api/routes/health.py`)
now also reports `schema: "ok" | "stale" | "unknown"` by comparing the DB's real
`alembic_version` row against the code's own Alembic head revision (read once at
import time via `ScriptDirectory.from_config`, not per request) — defense-in-depth
for any future deploy path that doesn't go through the compose `migrate` service (a
raw `docker compose up -d api`, a different orchestrator, a human skipping steps),
so a schema mismatch is a clear `/health` field instead of another cryptic 500 on the
first real query. (2) A root `Makefile` (`make up`) wraps `cp -n .env.example .env
&& docker compose up -d` into one command — `cp -n` (no-clobber) so re-running it
never overwrites an already-configured `.env`. The GitHub Wiki was checked and needs
no change: its Home page already explicitly defers all installation instructions to
the README rather than duplicating them.

**Phase 8 decision (recorded 2026-11-06):** Kubernetes manifests use **Kustomize**, not Helm — `kubectl` has Kustomize built in (no extra tooling), and plain YAML + a `kustomization.yaml` fits a single-environment (`kind`) demo better than a chart's templating layer. See `k8s/`. The scan `CronJob` is additive to the app's own internal ARQ cron (`cron(nightly_scan_all, ...)` in `app/tasks/worker.py`, already running wherever the worker Deployment runs) — it demonstrates the k8s-native primitive by hitting `POST /scan` against the committed `tests/fixtures/demo-store` fixture, not a replacement for the in-process schedule.

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

Explicitly **not** chosen: pure vector RAG, GraphRAG, a separate vector database, LangChain as the core. Post-1.0: reranking, query rewriting — the retrieval-debugging panel itself is now done (see below); reranking/query rewriting stay deferred since either adds a real per-query LLM cost decision against the budget cap that wasn't made yet.

**Retrieval-debugging panel (recorded 2026-11-07):** RRF fusion summed every signal's
rank into one `rrf_score` and discarded the per-signal detail entirely — no way to see
*why* a result was found (or why an expected one wasn't). `app/search/hybrid.py`'s
`_SEARCH_SQL` now tags each signal's CTE rows before fusing them and carries
`semantic_rank`/`keyword_rank`/`identifier_rank` (each `NULL` if that signal never
surfaced the chunk at all) through to `SearchResult`, both existing consumers
(`GET /search`, the agent's `search_modules` tool), and — the part that previously
stopped at the tool boundary — `_collect_sources`/`Source` in `app/agent/loop.py`,
which used to strip a `search_modules` result down to just `module_id`/`module_name`/
`relative_path` before it ever reached the `sources` SSE event. Every other tool
(`get_module`, `find_by_class`, etc.) has no ranking signal of its own, so these fields
stay `null` for sources that came from them — only a `search_modules` citation ever
carries real values. Frontend: `frontend/lib/chat-types.ts`'s `Source` type grew the
same four fields, and the chat page's `SourceChips` shows a small info-icon/tooltip
next to a source chip (reusing the same `Tooltip` primitive and pattern as the Stats
page's description tooltips) with e.g. "Semantic #2 · Keyword not found · Identifier
not found · RRF score 0.0328" — rendered only when at least one field is non-null, so
a plain `get_module`/`find_by_class` citation shows no icon at all.

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
rejects a mismatch with a 400 before saving, instead of only failing later.

**Re-embed workflow on embedding-model change (recorded 2026-11-07):** closes the gap
flagged above. `PATCH /settings/llm` now detects an *actual* change to the effective
embedding model (not just the field being present in the request body — re-sending
today's already-effective value, e.g. a form that always submits every field, must not
trigger anything) and, if any module is `up_to_date`, requires a new `confirm_reembed:
true` flag before proceeding — re-embedding a large fleet is real, billable work (the
same budget-consciousness this file already treats CVE/PHPStan checks as exempt from,
since those cost nothing), so this is never triggered silently just because
`embedding_model` changed. With confirmation, every `up_to_date` module flips to
`embedding` and gets a fresh `embed_chunks` job enqueued — a distinct `_job_id`
(`embed:{id}:{hash}:reembed:{model}`), not the one `synthesize_module` would normally
use for that same `(module_id, current_hash)` pair, since the module's own hash hasn't
changed here and reusing that job_id risks ARQ treating it as a duplicate of an
already-completed job and silently skipping it. No new per-chunk model/dimension
tracking column was added — a cache miss under the new model's name already triggers a
real re-embed call per chunk (`analysis_cache` is keyed by `(content_hash, model, ...)`
), so this only had to get each module's own job back into the queue, not change the
caching mechanism itself.

**Security review findings fixed (recorded 2026-11-06):** a full-project `/security-review`
(initial scan + independent verification sub-agents) found two real, confirmed HIGH
findings (9/10 and 8/10 confidence), both fixed:
1. `POST /scan`/`POST /scan/stream`/`POST /webhooks/scan` only checked
   `os.path.isdir(path)` — `settings.scan_roots` (`MAGEWIKI_SCAN_ROOT_1/2/3`) was
   previously only used for the `GET /scan-roots` UI hint and error-message text,
   never actually enforced as the access-control boundary this file already
   documented it as. Any reachable caller could scan arbitrary host paths the
   container could see (confirmed concretely: the default `/tmp` fixture mount, the
   app's own source tree, the base image's filesystem all qualify). Fixed with
   `Settings.is_within_scan_roots()` (`app/config.py`) — fails closed (no configured
   roots means nothing is scannable) — called from all three handlers. Tests needed
   their own scan roots widened (`tests/conftest.py` now sets
   `MAGEWIKI_SCAN_ROOT_1/2` to the repo's `tests/` dir and the system temp dir for the
   test session) since `demo_store_path`/`tmp_path`-based fixtures aren't under any
   real deployment's configured roots.
2. `PATCH /settings/llm` let `llm_api_base`/`embedding_api_base` change independently
   of `llm_api_key`/`embedding_api_key` — since every LLM/embedding call sends the
   stored key to whatever `api_base` is configured (the same mechanism the legitimate
   Ollama/custom-proxy BYOK path relies on), an unauthenticated caller could redirect
   an already-provisioned secret's destination without ever needing to know its
   value. Fixed: changing `*_api_base` when a key is already stored now requires
   providing `*_api_key` again in the same request. Deliberately not fixed by adding
   a full authentication system — this is a single-user local tool by design, and a
   blanket auth layer is a much bigger architectural decision than a security-bugfix
   pass should make unilaterally; this closes the specific secret-redirection
   primitive without expanding scope into a general access-control redesign.

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

**Synthesis reliability at real fleet scale (recorded 2026-11-07):** a real 760-module
store scan surfaced that `LLM_MODEL`'s cheap default (`anthropic/claude-haiku-5-5`)
fails `ModuleDoc` schema validation on ~341/760 modules (45%) even after the existing
corrective-reprompt retries (`app/analyzer/client.py`'s `_MAX_ATTEMPTS=2` in both
`_call_tool_use` and its `_call_plain_json` fallback — 4 real attempts, all exhausted).
Two distinct patterns, not one: ~309 modules with a required field outright missing
(`confidence`/`description`/`pm_text`), and 32 modules where the model returned `tags`
as bare strings (`"payments"`) instead of the required `{name, source, confidence}`
object. Fixed both without redesigning the retry machinery:
1. `Tag` (`app/analyzer/schemas.py`) now has a `model_validator(mode="before")` that
   coerces a bare string into `{name: <string>, source: "ai", confidence: 0.5}` before
   validation — a bare string is unambiguously AI-sourced (a parser-derived tag is
   never free-form text), so this closes the 32-module pattern outright rather than
   retrying for an object shape the model keeps not producing.
2. A new `SYNTHESIS_MODEL` setting (`app/config.py`, default empty = same as
   `LLM_MODEL`, no behavior change unless set) lets `synthesize_module` use a stronger
   model than `analyze_file`'s cheap per-file summaries — `resolve_synthesis_llm_config()`
   (`app/runtime_config.py`) reuses the same BYOK `api_key`/`api_base` as the main LLM
   config, only the model name differs, so it stays provider-agnostic rather than
   hardcoding Anthropic. This deployment's `.env` sets it to
   `anthropic/claude-sonnet-5-5` for the remaining ~309-module pattern. Checked the
   real cost before deciding: `analysis_cache` showed module_synthesis averaging
   ~6500 input / ~2500 output tokens on haiku (~$0.0019/module); sonnet's ~3x price
   (added to `pricing.py`'s fallback table) means resynthesizing the whole 760-module
   fleet costs roughly $1.50 → $4.50 one-time — negligible against the $20/month
   budget. Verified against two real, previously-failing modules (not mocks): both
   now persist a complete, schema-valid `ModuleDoc` under `anthropic/claude-sonnet-5-5`.
   Separately, and *not* caused by this: ~381/760 modules fail at the later
   `embed_chunks` step on a real `litellm.RateLimitError` — the configured
   `OPENAI_API_KEY` account has no credits remaining; that's an external billing
   issue for the operator to resolve, not a code bug.

**Scanner coverage: `.phtml` templates and GraphQL schemas (recorded 2026-11-07):**
flagged by a user comparing a module's synthesized `features` against what it
actually does — the scanner only ever discovered `.php` files
(`discovery.py`'s file walk, literally `.php`-suffix only). XML config has its
own dedicated structural parsers, but `.phtml` templates and
`etc/schema.graphqls` fell into neither category and were completely invisible
to the whole pipeline. `walk_module_php_files` → `walk_module_source_files`
now also matches `.phtml`, feeding the same per-file LLM-summary pipeline
(`hashing.py`) and PHP class cataloging (`php_classes.py`, which harmlessly
finds zero classes in a template file) — also benefits the deprecated-
annotation and hardcoded-secret scanners, which can equally find either
inside a `.phtml` file. New `app/scanner/graphql_schema.py` (`graphql-core`
dependency) parses `etc/schema.graphqls` into structured facts the same way
`di.xml`/`events.xml` already do: Query/Mutation/Subscription fields a module
adds or extends, plus custom type definitions, with the backing PHP resolver
class from Magento's `@resolver(class: "...")` convention when present (new
`graphql_fields` table, migration `0014`; wired into `ModuleFacts`/the
synthesis prompt and exposed on `ModuleDetail`).
**Known one-time cost, accepted deliberately:** widening file discovery means
every already-scanned module's `.phtml` files look "newly added" against the
old `FileHash` rows on the *next* rescan of an existing store — a real,
billable `analyze_file` job per `.phtml` file, fleet-wide, in that one scan.
This is the correct, necessary cost of actually closing the coverage gap (the
whole point is for the LLM to see `.phtml` content it never saw before), not
a bug — flagging it here so it isn't a surprise against `LLM_MONTHLY_BUDGET_USD`
the next time the real store is rescanned. Ongoing cost afterward is normal
(only files that actually change get re-analyzed, same as everything else).
Also hardened while in there: Phase A's parsing of `composer.json`/`di.xml`/
`events.xml`/`schema.graphqls` for each module had no `try/except` at all
(unlike `module.xml`'s, scoped per-module from the start) — an `OSError` from
any of them (a permission error, or a TOCTOU race between each parser's own
`.is_file()` check and its actual read) would abort scanning every remaining
module in the store, not just the one with the bad file. Now isolated the
same way `module.xml`'s own parse errors already were.

**Version source priority: Composer wins over `setup_version` (recorded
2026-11-07):** first fixed the narrower case — `module.xml`'s `setup_version`
is optional since Magento 2.3's declarative schema and often absent entirely
(`Amasty_Base` has no `setup_version` attribute at all) — by falling back to
`vendor/composer/installed.json`'s resolved version
(`app/scanner/installed_versions.py`) when `setup_version` was missing. Then
a second real case, caught by the project's own author looking at his own
module (`Ordo_Automation`): `setup_version` isn't just sometimes *absent*,
it's commonly *stale* — Ordo_Automation's module.xml says `"0.1.0"` even
though its composer.json has long since moved past that, because
`setup_version` is an internal Magento upgrade-script trigger that a module
using declarative schema never needs to bump again after its first release,
while composer.json's own `version` field keeps getting bumped on every real
release. Final priority, highest first: (1) composer.json's own `version`
field (now parsed into `ComposerResult.version`) — present for both
Amasty_Base and Ordo_Automation; (2) Composer's `installed.json`-resolved
version — covers a package with no `version` field in its own composer.json
at all; (3) `module.xml`'s `setup_version` — last resort. Composer's version
wins even when `setup_version` is present and non-empty, not only as a
fallback for when it's missing.

**PHPStan noise: `stubFiles` was the wrong parameter, and the sidecar's own
concurrency was silently losing results (recorded 2026-11-07):** a real
760-module store scan surfaced a single module (Ordo_Automation, 828 classes)
with 18049 `module_quality_findings`, almost all `phpstan_error` — verified
empirically (a minimal reproduction run directly against this project's own
`php-analyzer/magento-core.stub`) that the root cause was `phpstan.neon`
using `stubFiles` instead of `scanFiles`: `stubFiles` only refines types on
classes PHPStan already knows exist via the autoloader, it never makes an
unknown class exist in the first place — since this sidecar deliberately has
no real `magento/framework` installed (avoiding a repo.magento.com auth
requirement), every Magento class in the stub was genuinely unresolvable
under `stubFiles` regardless of the stub's content. Switched to `scanFiles`
and expanded the stub (global `__()`, `Magento\Framework\DataObject` with
`@method` tags — a bare `__call()` alone doesn't silence "undefined method",
confirmed empirically — and a fleshed-out `Magento\Framework\App\Action\Action`
base class with `getRequest()`/`$resultRedirectFactory`/`$messageManager`,
matching the exact noise patterns seen in the real report). Also excluded
`*/Test/*` (standard Magento module test layout, not Ordo-specific) after
measuring that 10204 of the remaining 11788 findings were PHPUnit mock/stub
chains (`$mock->expects()->method()`) inside test code, a different concern
than production business logic. Net effect on the real module: 14926 →
1584 `phpstan_error` findings (the residual noise is now mostly Magento's own
auto-generated `*Factory`/`*CollectionFactory` classes, which don't exist as
real files at all — closing that gap fully would need `bitexpert/phpstan-
magento`'s factory-autoloader plus a real `magentoRoot`, evaluated and
deliberately deferred: it requires PHPStan 2.x and a path to a full Magento
installation the sidecar doesn't have for a standalone-scanned module like
Ordo_Automation).

Separately, and more seriously: after this fix, the real DB still showed
*zero* `phpstan_error`/`php_compat_issue` rows for the same module, even
though a direct call to the sidecar returned 1584 findings. Root-caused via
the sidecar's own request log: `php -S`, the sidecar's built-in PHP dev
server, is single-threaded, so `check_php_static_analysis`'s four concurrent
`asyncio.gather()` calls queued up server-side regardless of the Python-side
concurrency — confirmed directly: phpstan's own request took 7s to process
but 83s from send to response, because it was last in the server's queue,
exceeding the client's 60s timeout. Every other failure mode in
`php_analyzer_client.py` already failed open with zero logging, so this
silently discarded two of four tools' results for any sufficiently large
module with no error anywhere. Fixed by calling the four tools *sequentially*
instead of concurrently (free: the single-threaded server was already
serializing them, so this changes zero real wall-clock time) so each gets a
fresh timeout window starting when it actually begins running, plus added
`logging.warning(..., exc_info=True)` on every fail-open path — previously
pure silent data loss, impossible to distinguish from "this tool genuinely
found nothing."

**A scanned module's own phpcs ruleset wins over a bare `--standard=Magento2`
(recorded 2026-11-07):** after the two fixes above, the real Ordo_Automation
module still showed 4707 findings — flagged by the user as still too many.
Root cause, found via the project's own author checking Ordo's own repo
directly: `phpcs_violation` was over 60% of the total (2842), and
`php-analyzer/public/index.php`'s `run_phpcs()` always ran a bare
`--standard=Magento2`, ignoring the scanned module's own `phpcs.xml.dist` —
Ordo's own ruleset deliberately excludes three whole rule families (comment-
block-on-every-typed-signature, property PHPDoc formatting, method-annotation
structure) as a documented style decision (typed native PHP signatures
instead of exhaustive docblocks), and Ordo's own CI respects that and passes
clean. MageWiki was re-flagging, as violations, exactly what the module's own
maintainers already decided aren't real problems — not noise in MageWiki's
config this time, a real gap in respecting the target project's own config.
Fixed: `run_phpcs()` now uses the module's own `phpcs.xml.dist`/`phpcs.xml`
when present (checked at the module root), falling back to the bare
`Magento2` ruleset only when neither exists.

While fixing this, also closed a second real gap found by directly checking:
phpcs/phpmd/rector weren't excluding `*/Test/*` at all (only `*/vendor/*`) —
phpstan.neon already excluded it (recorded above) but that fix never
propagated to the other three tools. `phpcs`'s `--ignore` and `rector.php`'s
`skip()` took the added pattern cleanly; `phpmd`'s own `--exclude` flag did
not — confirmed directly that combining `vendor/*,Test/*` (or even `Test/*`
alone) into one pattern silently excluded everything, not just Test/, rather
than erroring. Reverted phpmd's own flag to just `vendor/*` and instead added
the Test/ filter centrally in `php_analyzer_client.py`, after collecting all
four tools' results — this is now the one place the policy is guaranteed
correct regardless of any individual tool's own exclude-flag quirks. Verified
end-to-end against the real Ordo_Automation fixture: `phpcs_violation` 2842
→ 0 (legitimately clean against its own ruleset), total findings 4707 → 1736.

**php-analyzer runs three PHP versions side by side, picked per scanned
module (recorded 2026-11-07):** the remaining 1584 `phpstan_error` findings
were still mostly noise — real Magento core classes (not just bitexpert/
phpstan-magento's auto-generated-class magic) need the scanned store's own
real Composer autoloader to resolve at all, confirmed empirically:
`vendor/bitexpert/phpstan-magento`'s `magentoRoot` alone still left ordinary
classes like `Magento\Backend\Block\Template` as "extends unknown class".
Wiring in the real `vendor/autoload.php` immediately hit a real, structural
problem the user flagged directly: Composer's generated
`vendor/composer/platform_check.php` enforces a scanned module's own declared
PHP version requirement strictly, and it can't be disabled without mutating
the scanned module's own files (never done here) — a sidecar fixed to one
PHP version can never satisfy every scanned module's own requirement (Ordo
alone has required `>=8.4 <8.6` and, in its real, actively-developed repo
rather than the `vendor-src-sync` snapshot used for fixtures here, `>=8.3
<8.6`). Rejected a graceful-degrade-only fix (retry without the real
autoloader on failure) in favor of actually installing multiple PHP versions,
per explicit user request. `php-analyzer`'s Dockerfile now uses `alpine:edge`
(confirmed the only Alpine base packaging php83 **and** php84 **and** php85
side by side as of this writing — numbered releases top out at php84) with
all three installed as separate binaries; `app/scanner/php_analyzer_client.py`'s
`_pick_php_binary()` reuses the existing Composer-constraint overlap checker
(`app/scanner/semver.py`, already built for the CVE check) to pick the
highest of the three a scanned module's own `composer.json` php constraint
allows, defaulting to php84. The chosen binary runs all four tools, not just
phpstan, for consistency. `run_phpstan()` still retries without the real
autoloader if it fails for some other reason (e.g. the module's constraint
falls outside all three installed versions) — degraded, not zero, findings.

Two more real, structural bugs surfaced building this, both fixed: (1)
`%env(...)%` does not reliably interpolate for PHPStan's `bootstrapFiles`/
custom extension parameters — confirmed empirically (one left the literal
unsubstituted text in a file path; a different, unquoted attempt failed as a
Nette DI "Statement" object reaching code expecting a plain string) — fixed
by generating a small per-request overlay `.neon` file with the real paths
as literals, `include`-ing the real `phpstan.neon` from it, instead. (2) The
Dockerfile's `vendor/bin/phpcs --config-set installed_paths` override (from
before this session) had gone stale after `magento/magento-coding-standard`'s
major-version bump — it referenced `vendor/phpcompatibility/php-compatibility`,
which no longer exists (replaced by `vendor/magento/php-compatibility-fork`)
— removed entirely rather than re-hardcoded, since composer's own
`dealerdirect/phpcodesniffer-composer-installer` plugin already configures
this correctly on every install.

**PHPStan's own phpVersion auto-detection doesn't reach every rule
(recorded 2026-11-07):** after a `git pull` brought Ordo_Automation's real
fixture up to date (828 → 1514 classes), the real finding count — still
flagged as too high by the user — turned out to have a fourth real cause:
`classConstant.nativeTypeNotSupported` ("Class constants with native types
are supported only on PHP 8.3 and later") was firing on `private const array
X = [...]` even when the sidecar ran it under `php85`, and even though
PHPStan's own `--debug` output reported "PHP version for analysis: 8.4.27
(from runtime)" — confirmed via a minimal, config-free reproduction
(`level: 0`, no bitexpert, no overlay) that this is a genuine PHPStan 2.3.5
quirk: runtime auto-detection doesn't propagate to this specific
non-ignorable rule, but setting `phpVersion` explicitly as a literal integer
in the config does. `run_phpstan()`'s overlay config now always sets it,
mapped 1:1 from the chosen `php_binary` (`php83` → `80300`, etc.). Net:
1262 → 922 `phpstan_error` findings on the real, now-larger module.

**composer.json facts that were parsed but never surfaced anywhere
(recorded 2026-11-07):** flagged by a user looking at Ordo_Automation's own
real, current composer.json (not the `vendor-src-sync` snapshot) and asking
why `homepage`/`authors`/required PHP extensions weren't shown anywhere —
`license` turned out to have the exact same problem (parsed, stored on
`Module`, never exposed via the API at all). Added `homepage`, `authors`
("Name <email>" strings), and `php_extensions` (the `ext-*` keys `require`
already excludes from the CVE-check package list, since they have no
Packagist page) to `ComposerResult`/`Module`, and exposed all four
(including the pre-existing `license`) on `ModuleDetail`. Deliberately didn't
add composer `scripts`/`autoload`/`config.allow-plugins` in the same pass —
lower-value, more niche fields for a module catalog's own UI; worth adding
individually if ever asked for, not speculatively bundled in here.

**Composer scripts/autoload.psr-4/allow-plugins added (recorded
2026-11-08):** closes the "worth adding individually if ever asked for" note
right above, once actually asked for. `scripts` stores only the defined
script *names* (`composer.json` is untrusted third-party input, and a
script's command content isn't useful for a read-only catalog without
execution anyway — same reasoning as every other "facts from parsers, not
execution" decision in this file). `autoload.psr-4` stores the real
namespace → path map, normalizing Composer's string-or-array path shape to
one string per namespace. `config.allow-plugins` stores package name →
whether it's allowed to run as a Composer plugin. New `Module.composer_scripts`/
`composer_autoload_psr4`/`composer_allow_plugins` columns, exposed on
`ModuleDetail` and rendered on the module detail page the same way
`homepage`/`authors`/`php_extensions` already are. Verified against the real
Ordo_Automation fixture's actual composer.json (real `scripts`/`autoload.psr-4`/
`config.allow-plugins` entries), not just synthetic fixtures.

**Two more PHPStan settings adopted from a battle-tested internal Magento
scanner (recorded 2026-11-07):** the user asked directly whether php-analyzer
should be configurable the same way as "modularz" — a separate, independently
developed internal tool (Cognize's property; referenced here for concepts
only, per this file's own "nothing here is copied code" rule) that scans
real Magento modules under the identical constraint (no real
`vendor/magento/framework` install). Checked its config and adopted two
things fresh, not copied: (1) `treatPhpDocTypesAsCertain: false` — scanned
modules are third-party code this sidecar doesn't control, so an
inaccurate/incomplete `@param`/`@return` (common in real-world modules)
shouldn't be trusted as ground truth over what the code actually does; (2) a
non-empty top-level PHPStan JSON `errors` array alongside an empty `files`
array means PHPStan itself crashed (a config/internal error, not a genuine
"no findings" result) — modularz hits exactly this from bitexpert/
phpstan-magento's other autoloader services (Factory/Proxy/
ExtensionInterface) when `magentoRoot` isn't backed by a real Magento
install; this sidecar's own two cases (a real `vendor/autoload.php`, and the
no-op fallback) don't currently trigger it, but the check was added anyway
as defense against a gap that's real even though not yet hit here. Verified
against the real Ordo_Automation fixture: 1075 → 1064 `phpstan_error`
findings, confirming the fix changes real output, not just defensive code
that never fires.

**Real confidential-client-data leak via README/Wiki screenshots, and the fix
(recorded 2026-11-08):** a real violation of this section's own first rule. While
refreshing portfolio screenshots against the live local app, a screenshot of the
Modules page's "Scannable under" line and the Repos page showed the literal local
path of a real client's Magento store (configured as a second `MAGEWIKI_SCAN_ROOT`
alongside `magento-ordo-test` for unrelated real-world testing earlier the same
session — see the Composer path-repository/enabled-status-filter/multi-store
decision notes above, all of which used that same real store as genuine test data
without ever intending it to appear in a *published* artifact), and a third
screenshot showed real CVE/hardcoded-secret findings from a module inside that
client's actual deployment. All three were committed and pushed to the public repo
and wiki before being caught (by the user, not by the model).

Root cause: the model had already treated that store's path as ordinary real-world
verification data all session (used it directly in chat, in `list_modules` checks,
in SBOM tests) and knew it was a real client's store — but when the task shifted to
"capture screenshots of the live app for the README/Wiki," it was treated as a
purely visual/UI task, and the model never re-ran the "is this specific data safe to
publish" check this section already states as a hard rule, even though the rule was
already loaded in context the whole time. Browsing a live app and screenshotting
whatever happens to be in its database is not content-neutral just because the task
is framed as "take a screenshot."

Fix, in order: (1) deleted that client's ~741 scanned modules from the local dev
database entirely (cascaded via the existing `ON DELETE CASCADE` FKs — the client's
own files on disk were never touched, only this project's local index of having
scanned them) and removed it from `.env`'s `MAGEWIKI_SCAN_ROOT_*`, leaving only
`magento-ordo-test` (the real `magento/magento2` checkout + `Ordo_Automation`) as
configured; (2) recaptured every affected screenshot in both repos against only that
safe data; (3) used `git-filter-repo --strip-blobs-with-ids` to remove the specific
leaked blobs from **history**, not just supersede them with a new commit — a plain
new commit leaves the old blob fetchable by SHA indefinitely; (4) verified on fresh
clones from GitHub (not the locally-rewritten copies) that the old commit SHAs and
blob IDs are unreachable and that `git grep` for the client's name across every
commit in both repos' full history returns nothing; (5) force-pushed both repos
(explicit user authorization obtained first — this is exactly the kind of
destructive, public-history-rewriting action this file's own safety discipline
requires confirming before doing).

Going forward: before capturing or publishing *any* artifact derived from the live
app's actual current state (a screenshot, an exported CSV, a copy-pasted API
response, a demo recording), explicitly check what's currently configured/scanned —
`GET /scan-roots` and `GET /repos` — and confirm it's limited to this section's own
approved test data, as a deliberate step before capturing, not an afterthought
checked only if something looks wrong afterward. "It's just a UI screenshot" is not
an exemption from this file's test-data rule.

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
| 14 | Deeper structural facts: `webapi.xml` (REST/SOAP endpoints), `crontab.xml` (scheduled jobs), `db_schema.xml` (tables/columns), `system.xml` (admin config options) — same pattern as the "Scanner coverage: .phtml templates and GraphQL schemas" decision above (structured facts, not LLM-guessed), one new parser + table + prompt wiring per file type | Each shows up as its own structured fact block in the synthesis prompt and a `features[].source` a module's AI-written description can cite, the same way GraphQL fields already do |

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
nothing today is large enough to prove that's actually needed.

**Hash-skip for file-hash-dependent quality checks (recorded 2026-11-08):** the "nothing today
is large enough to prove that's actually needed" above got proven wrong — a real 751-module
store's nightly cron was hammering `php-analyzer` non-stop (confirmed directly: a no-op rescan of
that same store took 1518s). `_persist_module` (`app/scanner/orchestrator.py`) now skips
`composer_completeness_findings`/`scan_deprecated_annotations`/`scan_hardcoded_secrets`/
`check_php_static_analysis` entirely when `diff.is_empty()` (this module's own files are
byte-for-byte unchanged since last scan) — their result is purely a function of this module's own
file content, so it can't have changed either, and their existing `module_quality_findings` rows
are left untouched rather than deleted-and-reinserted. The three checks that depend on *external*
data (`security_advisory`, `abandoned_dependency`/`outdated_dependency`, Magento upgrade
readiness) always rerun regardless of `diff.is_empty()` — a new CVE or Magento release can make an
unchanged module newly non-compliant, so skipping those on file-hash alone would be wrong, not
just an optimization. `plugin_conflict` (see below) was never affected either way — it's a
separate fleet-wide pass, not part of this per-module path at all. Verified against the same real
751-module store, not just the unit test mocking call counts: a second, no-op rescan dropped from
1518s to 170s (~9x) with identical finding counts.

Also worth flagging: `ModuleSummary`
now carries 10 flat per-check-type count fields (3 added in Phase 9, 3 more in Phase 10, 4 more
here) — a generic `dict[check_type, count]` would scale better, but wasn't worth refactoring three
times' worth of already-shipped, working frontend code for a cleanliness win nobody asked for.
Worth doing if an even 5th wave of check types ever shows up. **Update (2026-11-07/08):** that
refactor happened by the time Phase 14 and the plugin-conflict/PhpMetrics check types below were
added — `finding_counts` is a plain `dict[str, int]` today (`app/schemas.py`), and
`frontend/components/quality-badges.tsx`'s `CHECK_TYPES` array is the one place a new check type
needs registering on the frontend **for the Modules list and per-module badges.** Two more waves
since this was first flagged, zero backend/frontend-shape changes needed either time — the "worth
doing if a 5th wave shows up" bar was already cleared. **Correction (2026-11-08):** "the one
place" was incomplete — see the Stats-page gap noted right below; `CHECK_TYPES` was never the only
frontend registration point to begin with, just the only one that happened to already cover every
check type that existed until this session.

**Stats page gap: four new check types had no tile (recorded 2026-11-08):** found
while refreshing the README/Wiki to reflect everything added this session —
`CHECK_TYPES` above already covered `phpmetrics_issue`/`plugin_conflict`/
`composer_conflict`/`webapi_route_conflict`, but `app/stats/page.tsx`'s `StatTile`s
are a separately hand-maintained list (unlike the badges, it groups several check
types into one human-readable tile, e.g. "Magento upgrade blockers," so it can't just
iterate `CHECK_TYPES` generically) — all four new check types were invisible on the
Stats dashboard even though they showed up correctly on the Modules page. Folded
`phpmetrics_issue` into the existing "PHP static-analysis findings" tile (same
conceptual bucket as phpstan/phpmd/phpcs/php-compat) and added a new "Cross-module
conflicts" tile summing `plugin_conflict`/`composer_conflict`/`webapi_route_conflict`.
Verified against the real, already-scanned fleet (not just the unit test's synthetic
counts): the real Stats page now shows "PHP static-analysis findings: 8659" and
"Cross-module conflicts: 316" instead of omitting them entirely.

**PhpMetrics added (recorded 2026-11-08):** closes the "dropped during scoping" gap immediately
above, flagged by the author asking directly what free scanners from `modularz`/v1's original
tool list MageWiki still didn't have. Unlike phpstan/phpmd/phpcs/rector, PhpMetrics' CLI
(`--report-json`) reports continuous metrics (complexity, maintainability index, coupling), not
discrete pass/fail violations — rather than inventing arbitrary thresholds on those raw numbers,
`--report-violations` emits an XML in the exact same "PMD Violation" shape phpmd itself produces,
encoding PhpMetrics' own built-in risk rules (confirmed empirically against a real 1514-class
module: "Too complex method code," "Probably bugged" via Halstead bug prediction, "Blob / God
object," "Stable Dependencies/Abstractions Principle" for package-level coupling — 138 real
findings, not a synthetic test). The one real integration wrinkle: PhpMetrics' violations key by
class FQCN (or, for a package-level rule, a bare namespace prefix ending in `\`) rather than a
real file path like every other tool here — `app/scanner/php_analyzer_client.py` resolves this
against the *same* `fqcn_to_file` dict `orchestrator.py` already builds from
`catalog_module_classes()`'s own result, passed in as a new optional argument, rather than a DB
round-trip — keeps `check_php_static_analysis` genuinely session-independent so it can keep
running concurrently with the other quality checks. A namespace prefix never matches a real FQCN,
so a package-level finding naturally resolves to `file_path=None`, which is correct — there isn't
one. New `phpmetrics_issue` check_type (migration `0023`), severity `"warning"` to match the rest
of the PHP toolchain family. The Test/-directory exclusion filter (shared across all five tools)
had to switch from a `"/Test/"` substring check to a path-*segment* check (`"Test" in
Path(...).parts`), since phpmetrics' resolved paths are already-relative (`"Test/Unit/Foo.php"`,
no leading `/`) unlike the other four tools' absolute paths — a substring check would have missed
that shape.

**GitHub API degradation during this same build (recorded 2026-11-08):** Composer's
`--prefer-dist` kept failing with `curl error 28/56` timeouts and HTTP 504s against
`api.github.com`'s zipball endpoint — not a one-off blip: confirmed as a real, officially
acknowledged GitHub incident (githubstatus.com: "Increase in timeouts for some unauthenticated
users," API Requests degraded, started that day) explicitly scoped to *unauthenticated* traffic,
which is exactly what an anonymous `composer install` makes. Two durable fixes, both kept
permanently (not reverted once the incident resolved): (1) `php-analyzer/Dockerfile`'s
`composer install` now always passes `--prefer-source` (git clone over `github.com`) instead of
the default `--prefer-dist` — confirmed more reliable for this dependency set independent of the
incident, and `git` was already installed for this exact reason; (2) added an *optional* Docker
build secret (`--mount=type=secret,id=github_token`) that authenticates Composer's GitHub
requests when the build is invoked with `--secret id=github_token,src=<file>` — a no-op (`||
true`) when no secret is passed, so every existing build (CI, every other contributor) behaves
identically to before. Authenticated requests aren't subject to GitHub's unauthenticated-tier
rate limits/degradation at all, which is a genuine, permanent resilience improvement regardless
of this specific incident, not just a workaround for it. Verified directly: the exact same
dependency set that failed repeatedly over roughly an hour on `--prefer-dist`/anonymous
`--prefer-source` succeeded in 162s once a GitHub token was supplied via the secret mount.

**Composer version-conflict detection (recorded 2026-11-08):** the third of three new scanner
features added the same session, after the user asked directly what MageWiki was still missing
for full SCA (Software Composition Analysis) coverage. Real impact, not theoretical:
`composer install` resolves exactly *one* version of a package for an entire Composer project: if
two modules in the same store require incompatible ranges of the same package (a very real case
for `magento/module-*` packages between extensions targeting different Magento versions, as well
as ordinary third-party libraries), the install fails for the whole store, not just the
conflicting modules. New `app/scanner/composer_conflicts.py` reuses the exact same fleet-wide
Phase-C pattern as plugin-conflict detection (groups every module's already-cataloged
`composer_package_requirements` by package name, flags a pair across 2+ distinct modules whose
constraints don't overlap via `semver.py`'s existing `constraints_overlap`) and the exact same
"flag a concrete conflicting pair, don't solve full N-way SAT across every requirer" pragmatism.
Magento's own packages are deliberately *not* excluded here, unlike the CVE check — that
exclusion exists only because Magento's packages aren't resolvable via public Packagist, but this
check never calls Packagist at all, just compares constraint strings directly. New
`composer_conflict` check_type (migration `0024`), severity `"warning"`, one row per involved
module — the `finding_counts`/`CHECK_TYPES` registration note right after the Phase 12 decision
above covers this and the other new check types added the same session.

**webapi.xml route-conflict detection (recorded 2026-11-08):** the third of a run of
"po kolei" (one after another) cross-module conflict checks the user asked for in one sitting,
after the composer-conflict one above. Same fleet-wide Phase-C pattern again, this time over
`webapi_routes` (Phase 14's structured REST-endpoint facts): two or more modules declaring the
exact same `(url, http_method)` pair is a real conflict, not theoretical — Magento merges every
installed module's route declarations into one table keyed by `(url, method)` at compile time,
and an exact duplicate is genuinely ambiguous (one module's service silently wins depending on
compilation order, not a documented override mechanism the way a deliberate route override
works). Matched on the literal `url` string only, not on path-parameter shape — `/V1/foo/:id` and
`/V1/foo/:bar` are treated as different routes even though both would collide on a real request —
deliberately conservative, same "flag a concrete, certain conflict" pragmatism as the two checks
above, to avoid a false positive MageWiki can't actually be sure about. New
`webapi_route_conflict` check_type (migration `0025`), severity `"warning"`.

**db_schema.xml column-conflict detection (recorded 2026-11-08):** the fourth and
last of the "po kolei" cross-module conflict checks. Unlike the three above, this one
needed the parser extended first: `db_schema_xml.py`'s scope was deliberately
table-level only since Phase 14 (name/comment/column count — "a column child table as
a natural later extension if ever needed," per that decision note), so there was no
per-column data to compare across modules yet. `parse_db_schema_xml()` now also
returns a flat `DbColumnEntry` per column (`table_name`/`column_name`/`xsi_type`/
`nullable`, read via lxml's Clark-notation `{http://www.w3.org/2001/XMLSchema-instance}type`
for the namespaced `xsi:type` attribute — verified empirically against a real
namespaced fixture rather than assumed) — still not a full breakdown
(length/identity/default aren't captured, since nothing needs them yet), persisted to
a new `db_columns` table (migration `0026`) via the same generic
`_sync_module_children` helper every other 1:N fact table already uses.

The conflict itself: two or more modules declaring the same `(table_name,
column_name)` with a different `xsi:type` or a different `nullable` value. Real
impact, not theoretical — Magento's declarative schema merges every module's
db_schema.xml by table/column name into one final definition in module-sequence
order, so a genuine type/nullability disagreement means one module's definition
silently wins and the other module's own assumption about that column can be wrong at
runtime. Same fleet-wide Phase-C pattern as the three checks above, same "flag a
concrete, certain conflict" pragmatism (only `xsi:type`/`nullable` compared, not the
unparsed length/identity/default). New `db_schema_conflict` check_type (migration
`0027`).

Also folded into the same session: the Stats page (`frontend/app/stats/page.tsx`)
had a real gap found while refreshing the README/Wiki for everything added
today — its `StatTile`s are a separately hand-maintained list, not generic over
`CHECK_TYPES`, so `phpmetrics_issue`/`plugin_conflict`/`composer_conflict`/
`webapi_route_conflict` were all invisible there even though they already showed up
correctly on the Modules page; see the dedicated note above. `db_schema_conflict` is
folded into that same new "Cross-module conflicts" tile from day one.

**Circular module.xml dependency detection (recorded 2026-11-08):** the first of a
second round of roadmap ideas the user asked to brainstorm, then work through "po
kolei" again, once the original four cross-module conflict checks were done. Module A
sequenced after B, after C, after A. Unlike the other four checks in this family,
this one is a guaranteed break, not an ambiguous-but-working merge: Magento's own
`setup:upgrade` explicitly detects a circular `<sequence>` and fails outright
("Circular sequence reference ... detected") — the store genuinely can't be installed
or upgraded until the cycle is broken. Reuses `module_dependencies` (already
populated from `module.xml`'s `<sequence>`, and already the data source for the
dependency graph) with zero schema change.

`app/scanner/circular_dependencies.py`'s `detect_circular_dependencies()` builds the
dependency graph purely from `ModuleDependency` rows (no separate "every module in
the repo" query needed — a node with no outgoing `<sequence>` edge of its own can
never close a cycle, so it's structurally irrelevant to this check either way) and
finds cycles via a standard white/gray/black DFS, reporting one representative path
per distinct cycle rather than enumerating every possible cycle in a graph with
multiple overlapping ones — same "flag a concrete, certain conflict" pragmatism as
the other checks in this file, not an attempt at exhaustive graph analysis. Despite
being a guaranteed break rather than an ambiguous merge, kept severity `"warning"`
for consistency with the rest of the cross-module-conflict family (all four existing
checks already default new check types to `"warning"` per the Phase 12 decision, and
there's still no "blocking" gate concept for this family specifically). New
`circular_dependency` check_type (migration `0028`), folded into the "Cross-module
conflicts" Stats tile alongside the other four.

**SBOM export (recorded 2026-11-08):** the second roadmap idea from the same
brainstorm, "po kolei" after circular-dependency detection. Closes a real, named SCA
gap (flagged when the user directly asked "a czego nam brakuje do SCA?" earlier this
session): the existing CVE/abandoned-dependency checks already evaluate composer
name/version/license data per module, but nothing exported it in a standard,
tool-consumable format a security team could feed into Dependency-Track or another
SBOM consumer. New `GET /repos/sbom?repo_root=...` (`app/sbom.py`'s pure
`build_cyclonedx_sbom()`) returns a CycloneDX 1.5 JSON document — one "library"
component per module currently scanned under that repo_root, built entirely from
data already parsed and persisted (`Module.composer_name`/`setup_version` — the
field that actually holds the resolved version, despite its name, per the "Version
source priority" decision — `license`, `homepage`), no new scan or external call.
Deliberately a flat `components` list with no `dependencies` graph section (CycloneDX
allows omitting it) — the existing per-module dependency graph already answers "what
does X depend on"; this just answers "what's actually installed," which doesn't need
the edges. `license` entries use CycloneDX's free-text `license.name` field, never
`license.id` (which requires strict SPDX-identifier validation) — correct for every
stored value without needing to validate it against the full SPDX list first.
Frontend: a "Download SBOM" button on each Repos page card, implemented as a real
`<button>` nested inside the card's existing `<Link>` (valid HTML — only anchor-in-
anchor nesting is invalid) with `stopPropagation`/`preventDefault` so clicking it
doesn't trigger the card's own navigation; triggers the download via `window.open(url,
"_self")` rather than `window.location.href` specifically to avoid a
`no-location-assign-relative-destination` ESLint false-positive (the rule can't tell
the destination is cross-origin, to the API server, not an internal Next.js route).
Verified end-to-end against the real, already-scanned `.../magento-ordo-test/magento`
repo (not just unit tests): the button genuinely downloaded a 47-component, valid
CycloneDX document to disk without navigating away from the Repos page.

**Stale generated OpenAPI types, found while regenerating for the SBOM endpoint
(recorded 2026-11-08):** `frontend/lib/api-types.ts` is generated from the live
backend (`npm run gen:types`), but nothing in CI or this project's working method
ever re-ran that generation after a backend schema changed — regenerating it now (a
necessary step so the new `/repos/sbom` path has a type) surfaced that
`LlmSettingsUpdate.confirm_reembed` had been completely absent from the committed
types file since the re-embed-workflow feature shipped, several sessions ago.
Worse than a types-only gap: `frontend/app/settings/page.tsx`'s embedding-model save
flow never sent `confirm_reembed` at all and had no UI to handle the backend's actual
400 response asking for it — meaning changing the embedding model via this page, with
any `up_to_date` modules present, was silently broken end-to-end (the user would see
a raw error string with no way to proceed) since the day that backend feature
shipped, never caught because the stale types file let the mismatched frontend code
typecheck clean. Fixed properly rather than just satisfying the type: `saveEmbedding()`
now remembers its attempted update, and a "Confirm re-embed" button appears
specifically when the save fails with the backend's own re-embed-confirmation message,
resending the same update with `confirm_reembed: true`. `saveLlm()` and both "Reset to
.env default" buttons needed `confirm_reembed: false` added too, now that the
regenerated type makes the field required (openapi-typescript's documented behavior
for a field with a schema `default`: always-present rather than optional). No CI
change was made to auto-regenerate this file going forward — flagging here as a
known gap rather than building out a regeneration-drift-detection step this session
didn't ask for.

**Regression found while reading this same hash-skip code for the next roadmap item
(recorded 2026-11-08):** `_FILE_HASH_DEPENDENT_CHECK_TYPES` (see "Hash-skip for
file-hash-dependent quality checks" above) listed `phpstan_error`/`phpmd_issue`/
`phpcs_violation`/`php_compat_issue` but not `phpmetrics_issue` — PhpMetrics shipped
in a later session than the hash-skip tuple did, and nothing updated it. Net effect,
confirmed with a new regression test before fixing it (seeded a real
`phpmetrics_issue` finding, rescanned with no file changes, found it deleted and
never restored): a no-op rescan's early cleanup deletes every finding whose
check_type isn't in this tuple, while the later skip of `check_php_static_analysis`
itself (the same function that would recompute `phpmetrics_issue`) means it was never
replaced — a module's PhpMetrics findings were silently wiped on the very first
no-op rescan after they were created, and wouldn't come back until that module's
files changed again. Fixed by adding `phpmetrics_issue` to the tuple. Checked the
real DB before assuming data loss: still showed the original 138 real findings on
Ordo_Automation, so no module had actually hit a no-op rescan since PhpMetrics
shipped — this closes a real but not-yet-triggered data-loss bug, not a repair job.

**License-risk check (recorded 2026-11-08):** the third roadmap idea from the same
brainstorm, "po kolei" after SBOM export. Per-module, not fleet-wide (unlike the
conflict-detection family above) — `app/scanner/license_check.py`'s
`check_license_risk()` flags a module whose own composer.json declares a
strong-copyleft license (`GPL-`/`AGPL-`/`SSPL-` prefixes only; LGPL deliberately
excluded as lower-risk/debatable, same "flag a concrete, certain signal" pragmatism
as the rest of this file). Deliberately does *not* duplicate
`composer_completeness_findings()`'s existing "composer.json is missing license"
finding — a missing license was already covered; this only adds the complementary
signal of a license that *is* declared but carries real redistribution obligations.
New `license_risk` check_type (migration `0029`), added to
`_FILE_HASH_DEPENDENT_CHECK_TYPES` alongside `composer_completeness` since it's
purely a function of composer.json's own license field. Own "License risks" Stats
tile (not folded into "Cross-module conflicts" — this isn't a cross-module conflict
at all, just a per-module compliance signal).

**License-risk prefixes made configurable (recorded 2026-11-08):** the
`GPL-`/`AGPL-`/`SSPL-` list above was hardcoded, but what counts as "risky" is
a legal/business judgment call that varies by operator, not a technical fact
— unlike every other quality check in this file, which flags a concrete,
certain signal rather than a policy opinion. New `LICENSE_RISK_PREFIXES`
setting (`.env`, comma-separated, case-insensitive; default unchanged).
Empty disables the check entirely, for an operator who's already reviewed
their fleet's licenses and decided it doesn't apply to them.
`check_license_risk()` keeps the original tuple as its default parameter
(so the many call sites that don't care still work unchanged) and the
orchestrator passes `settings.license_risk_prefix_tuple` explicitly.

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

**Phase 14 built, plus two extra categories (recorded 2026-11-07):** done in full
(`webapi.xml`, `crontab.xml`, `db_schema.xml`, `system.xml`), plus two more structural
facts identified in the same review: `di.xml`'s `<virtualType>` (only `<preference>`/
`<plugin>` were parsed from that same file before — a common pattern composing UI
Component data providers and collections with preset filters) and the message-queue
topology spread across `communication.xml`/`queue_topology.xml`/`queue_consumer.xml`
(merged by topic/queue name into one `queue_bindings` fact per binding, since real
modules — e.g. Ordo_Automation — describe the same queue from three different angles
across those three files). `system.xml` directly closes a real gap: `config_options`
in the synthesis prompt previously asked the LLM to guess "system.xml-style
configuration keys evident from the facts above" — it now transcribes real parsed
facts instead. `db_schema.xml` scope is table-level (name/comment/column count), not
a full column-by-column breakdown — already a real fact for synthesis, with a column
child table as a natural later extension if ever needed.

None of the six get a dedicated UI card on the module page — checked first, and
`di_preferences`/`di_plugins`/`event_observers`/`graphql_fields` (already-exposed,
structurally identical cases) don't have one either; the established pattern is
parsed fact -> synthesis prompt -> AI-written prose in the README's "For developers"
section, with the raw structured data available over the API for the agent's SQL
tools (`find_by_event` etc.), not for a redundant UI card duplicating the prose.
`Module` lost nothing: all six attach as new child tables via the existing generic
`_sync_module_children` helper, same pattern as the four cases above.

Caught and fixed one process gap while building this: a new Alembic migration was
applied to the ephemeral pytest database (via `tests/conftest.py`'s own
`alembic upgrade head`) but not to the real dev database, since those are separate
databases — the live app crashed ("Failed to load module") the moment the orchestrator
code started querying tables that didn't exist yet outside the test DB. Fixed by
running `alembic upgrade head` against the dev database immediately after each new
migration from then on, not batched at the end.

Verified end-to-end against the real Ordo_Automation fixture (not just unit tests):
a real rescan populated `cron_jobs` (19), `webapi_routes` (57), `config_fields` (57),
`db_tables` (36), and `queue_bindings` (3) with real data; `di_virtual_types` needed a
real core Magento module instead (Ordo's own `di.xml` declares none) — verified
against `vendor/magento/module-catalog`'s real `di.xml`, then that one-off
verification module was deleted again (not something the user asked to add to the
catalog).

**Plugin-conflict detection (recorded 2026-11-07):** closes the one item named in this
file's own original vision statement ("Later: cron/webhook, BYOK, Ollama, dependency
graph, **plugin-conflict detection**, evaluation") that was never actually built, even
though everything else on that list was. The data was already there — `di_plugins`
(Phase 1) records `intercepted_type`/`plugin_class`/`sort_order` per module — but di.xml
never declares *which method* a plugin targets or *which kind* (before/after/around) it
is, only which class it intercepts; that has to be derived from the plugin class's own
method names (Magento's own convention: `before<Method>`/`after<Method>`/
`around<Method>`), which weren't being correlated across modules anywhere. New
`app/scanner/plugin_conflicts.py` does this: groups every module's plugins (fleet-wide,
by `repo_root`) by `(intercepted_type, target_method)`, using each plugin class's own
already-cataloged `php_class_methods` rows to resolve its real hook kind, and flags a
conflict only when **at least two different modules** are involved and either (a) 2+
of them define an `around` hook on the same method — arounds can silently suppress each
other depending on execution order, which is not guaranteed — or (b) they collide on
the exact same effective `sortOrder` (missing treated as the real Magento default, 0).
A plugin whose class's methods aren't known at all (never cataloged) is skipped rather
than guessed at — deterministic-only, consistent with every other parser-derived check
in this file. New `plugin_conflict` check_type (migration `0022`) reuses the generic
`module_quality_findings` table unchanged, one row per involved module so it surfaces on
every affected module's own page, and the new entry in
`frontend/components/quality-badges.tsx`'s `CHECK_TYPES` (the single source of truth
that already cascades to modules/repos/stats automatically) was the only frontend
change needed.

This runs as a new Phase C in `scan_repository_events()`/`_run_scan`, after the
existing per-module Phase A/B loop — it needs every scanned module's `di_plugins` *and*
`php_class_methods` already committed (same reason Phase A/B are split at all: a
plugin's class, and therefore which method it hooks, can live in a different module
than the one declaring the plugin in di.xml), and it recomputes across the *whole*
repo_root's already-persisted modules, not just the ones in the current scan, so even a
single-module scan still catches a conflict against a module scanned previously.
Verified end-to-end with a real two-module orchestrator-level test (not just the pure
detection function in isolation): two fixture modules each declaring an `aroundSave`
plugin on the same shared type produce exactly one `plugin_conflict` finding on each
module, and a sibling case (different methods, same class) correctly produces none.

### Backlog: porting ideas from v1

The author previously built a PHP tool for his employer Cognize — the predecessor MageWiki-AI (the open-source Python rewrite) succeeds, referred to here only as "v1" since it's Cognize's property. Phases 9–12 above come from a curated review of what v1 does in production; the full inventory (what's ported, what's skipped as Cognize-internal, and the detailed CVE-check design) lives in `docs/v1-port-roadmap.md`. Nothing here is copied code — concepts only, per the "no client-confidential code" rule below.

**CI tooling for MageWiki's own codebase (recorded 2026-11-06):** the product runs
extensive static analysis against *scanned Magento stores* (PHPStan/PHPMD/phpcs/
Rector, CVE checks), but MageWiki's own CI had nothing beyond lint/type-check/tests —
prompted by GitHub surfacing "30 vulnerabilities (7 high, 18 moderate, 5 low)" via
Dependabot on a routine push, alerts that existed but were invisible outside the
GitHub UI. Added four things: `gitleaks` secret scanning (new `secret-scan` job,
every push/PR); `pip-audit`/`npm audit` dependency vulnerability scanning in the
existing `backend`/`frontend` jobs, plus `.github/dependabot.yml` for automatic
weekly update PRs (pip, npm, github-actions ecosystems); `pytest-cov` +
`codecov/codecov-action` for real coverage reporting (81% today) — needs the
Codecov GitHub App installed on the account, a manual one-time step; and a new
`e2e-smoke` job that `docker compose up`s the real images (same ones `docker-build`
only checks *compile*, not that they *run*) and Playwright-checks `/modules`
actually boots and renders — proving a real deploy works, which nothing today
verified.

`pip-audit`'s step is deliberately `continue-on-error: true` for now, not silently
ignored: of the original 3 real findings (not counting pip/poetry/setuptools/virtualenv
noise from scanning the whole container instead of just the project's own
`poetry.lock` — verified `poetry export | pip-audit -r` is the correctly-scoped
command), `lxml` (directly pinned) was bumped `^5.3` → `^6.1` immediately since it
was safe to do standalone; `starlette`/`filelock` were transitive and blocked by
fastapi's own `<0.47.0` pin. `npm audit --audit-level=high` is fully blocking already
— the 13 frontend findings are all moderate/low, transitive through `shadcn`'s own
dev-tooling deps (not runtime code), so the threshold passes clean without needing the
same carve-out.

**Dependency refresh (recorded 2026-11-07):** the deferred fastapi bump above is now
done — `fastapi` `^0.115` → `^0.162` (with `starlette`, `mcp` `^1.1` → `^2.3`,
`asyncpg`, `tree-sitter-php`, pytest all bumped alongside, full suite re-verified
225/225 green both before and after, since the one failure seen mid-upgrade
reproduced as flaky in isolation and vanished on rerun — not a regression). This
unblocked `starlette`'s CVE but not `filelock`'s: `filelock` is pinned `<4.0` by
`litellm` itself (not by fastapi/starlette as the note above assumed), and no newer
litellm release exists yet to relax that. Checked whether litellm's own `filelock`
usage could be affected before forcing it: `litellm` only imports `filelock` from its
own CLI/proxy-client tooling (`litellm/proxy/client/cli/commands/*.py`), which this
app never invokes (only `litellm.acompletion`/`aembedding` are ever called) — so
`backend/Dockerfile` force-installs `filelock>=4.0.9` via a `pip install --no-deps`
step right after `poetry install`, out-of-band of the lock file, closing the real CVE
without waiting on litellm. Revisit by removing that step once litellm relaxes its own
pin and `filelock` can go back through `poetry update` normally. Still genuinely
blocked (version-lag only, no CVE, so not worth the same force-override treatment):
`redis` (`arq` pins `<6`), `huggingface-hub`/`importlib-metadata`/`python-dateutil`
(pinned by `litellm`/`botocore`'s own upper bounds). Frontend's `typescript` stays at
5.9.3 — `typescript-eslint` requires `<6.1.0` and `openapi-typescript` requires `^5.x`,
neither has released support for TypeScript 7 yet.

**Backend Python runtime bumped to 3.13 (recorded 2026-11-07):** closes the drift
flagged above — `backend/pyproject.toml`'s `python = ">=3.11,<3.15"` already allowed
a newer interpreter, but `backend/Dockerfile` still ran `python:3.11-slim`. Checked the
precondition before bumping: all three C-extension dependencies
(`tree-sitter-php`, `asyncpg`, `lxml`) ship wheels compatible with 3.13 — confirmed by
actually building the image (fast install, no compiler invoked) rather than trusting
PyPI's file-list tags at a glance, which first looked like `tree-sitter-php` had no
3.12/3.13 wheel at all until it turned out its wheels use the `cp310-abi3` stable-ABI
tag (forward-compatible with every later CPython, not version-specific per release).
Verified end-to-end on the real image, not just a standalone build: `docker compose
build api worker` + `up`, then inside the real running container — `python --version`
reports 3.13.18, `GET /health` returns `schema: "ok"`, the full suite passes
(452/452; the +1 from the usual 453 is a fixture-path-only skip from a narrower ad-hoc
`docker run` during investigation, not a real count — the final compose-based run is
the one that counts), `ruff check` and `mypy app` both clean. Also bumped
`.github/actions/setup-backend-env/action.yml`'s separately-pinned
`actions/setup-python` version (3.11 → 3.13) — the same composite action every CI job
that needs a backend environment uses, so this was the second place that had quietly
drifted from the Dockerfile besides the one already found. Landed on 3.13 (mature,
broad wheel support) rather than the newest release, per the original plan.

**Still open: filelock override removal.** The `backend/Dockerfile` `pip install
--no-deps "filelock>=4.0.9,<5"` step (see "Dependency refresh" above) is still needed —
re-checked PyPI directly: litellm's latest published release (1.108.2, same as
installed) still requires `filelock<4.0,>=3.16.1`. Revisit once a newer litellm relaxes
that pin.

**100% coverage required in CI (recorded 2026-11-07):** closes the item above —
tests were written to close the real gap first (backend: 100% lines, 453/453 tests;
frontend: 100% statements/lines/functions, 97%+ branches, 192/192 tests across 28
files, using the vitest runner added below), *then* the gate was raised, not the
other way around. Two small real cleanups fell out of chasing the last few points:
`frontend/app/modules/page.tsx`'s `startScan()` had a redundant internal
`if (!trimmed || scanStatus === "running") return` guard — provably dead code, since
its only caller is a submit button already `disabled` in exactly those two
conditions — removed rather than tested or pragma'd. `frontend/components/ui/table.tsx`'s
vendored `TableFooter`/`TableCaption` and a standalone `frontend/lib/utils.ts`
(a one-line `cn` re-export nothing imported — everything imports `cn` straight from
the `"cn"` package instead) were genuinely unused and deleted outright, same
principle. The remaining ~3% of frontend *branch* coverage (two optional-chaining/
nested-markdown edge cases) was left as-is — branch coverage was never the metric
this project's "100%" bar has tracked (backend's own coverage.py config doesn't even
instrument branches, only lines, per the `concurrency` note above), and line/
statement/function coverage is genuinely 100% on both sides.

Root `codecov.yml` now sets `project` (per `backend`/`frontend` flag) and `patch`
targets to 100% with `threshold: 0%` — validated against Codecov's own `/validate`
endpoint before committing. CI's `frontend` job switched from `npm run test:unit` to
a new `npm run test:coverage` (`vitest run --coverage`, lcov reporter) and gained its
own `codecov/codecov-action` upload step (`flags: frontend`) — previously only the
`backend` job uploaded anything, so frontend coverage was invisible to Codecov
entirely, not just unenforced. The backend upload step gained `flags: backend` to
match. `frontend/eslint.config.mjs` also needed `coverage/**` added to its ignores —
latent gap (lint happens to run before the coverage dir exists in CI today, but not
when run locally after a coverage run).

**Frontend unit-test runner added: vitest (recorded 2026-11-07):** a full-repo
code review ahead of the public release flagged `frontend/lib/sse.ts` (SSE
parsing, shared by chat and scan streaming) as risky, untested logic — the
frontend previously had no unit-test runner at all, only Playwright e2e.
Picked vitest over jest for zero-config TypeScript/ESM support matching this
project's existing tooling (Vite-free Next.js app, but vitest needs no bundler
coupling to work). While adding tests, fixed two real gaps in `sse.ts` itself:
`parseSseBlock` took only the first "data: " line, not spec-compliant for
multi-line data (latent, since the only real producer, `format_sse()`, never
emits multi-line data); and a single malformed event's `JSON.parse` threw
uncaught, killing the whole stream over one bad frame instead of skipping it.
Also best-effort parses a trailing block with no closing blank line at stream
end, previously dropped silently. Wired `npm run test:unit` into the
`frontend` CI job, after lint and before build. This is also step one of the
"require 100% CI coverage" backlog item above — the frontend side of that
needed a unit-test runner to exist before any frontend file could count
toward it.

**Code-scanning/Dependabot alert triage (recorded 2026-11-07):** reviewed all 448 open
GitHub code-scanning alerts and 15 open Dependabot alerts. One real bug found and
fixed: `_validate_scan_path()` (`app/api/routes/modules.py`) and `webhook_scan()`
(`app/api/routes/webhooks.py`) both checked `os.path.isdir(path) or not
is_within_scan_roots(path)` — `isdir()` ran on the raw, unvalidated path before the
scan-roots containment check, not after it as the comments next to both already
implied. Swapped the order so containment is checked first; all 21 tests covering
scan-path/webhook validation still pass. Everything else was noise, not a bug, and
dismissed on GitHub with an explanatory comment rather than left open: the other 20
CodeQL `py/path-injection` alerts are downstream of that same already-validated path
and CodeQL's taint analysis doesn't trace the custom sanitizer across the call graph
(false positive); all 427 Trivy alerts are in the `magewiki-backend-ci`/
`magewiki-frontend-ci` images' base-tool layers (pip/poetry/setuptools/virtualenv,
npm's own bundled deps) rather than the app's runtime dependencies — the same scoping
gap the CI-tooling note above already named for `pip-audit`/`npm audit` (won't fix);
and the 13 `filelock` Dependabot alerts are already closed in practice by the
Dockerfile override above — Dependabot just scans `poetry.lock`, which still shows the
pre-override `3.32.7` (inaccurate). Left open, no action: the 2 remaining npm alerts
(`minimatch`, `deepmerge`), both already at the newest version available within their
locked major via `shadcn`/`openapi-typescript`'s own transitive pins, matching the
existing accepted-risk note above for frontend dev-tooling deps.

**First-run onboarding wizard (recorded 2026-11-08):** flagged by the author relaying a
colleague's confusion — a fellow developer couldn't tell from the running app alone
whether MageWiki-AI needed a paid API key/subscription just to start using it, even
though the README already answers this (scanner is 100% free and local; an API key is
needed only for the two AI features, billed directly by the provider, capped by
`LLM_MONTHLY_BUDGET_USD`). That answer living only in the README, not in the app
itself, was the actual gap. New `components/onboarding-wizard.tsx`: a 4-step modal
(what MageWiki-AI is / how to configure scan roots and start a scan, with live
`GET /scan-roots` data inline / that AI features are optional and where to add a key /
a closing link to the Wiki) built on a new `components/ui/dialog.tsx` primitive
(`@base-ui/react/dialog`, same wrapping pattern as the existing `tooltip.tsx`). Shows
automatically on first visit (`localStorage`, never during SSR — read via
`useSyncExternalStore`, the same pattern `lib/use-query-param.ts` already established
for "browser-only state, never during SSR," chosen specifically to avoid a
`react-hooks/set-state-in-effect` lint violation an earlier `useEffect`-based draft
hit), reachable again anytime via a new "?" button in `SiteHeader` through a small
`OnboardingProvider`/`useOnboarding()` context (mounted once in `app/providers.tsx`,
wrapping every page). Verified live in a real browser against the real app, not just
unit tests: all 4 steps, the live scan-roots data, dismissal persisting across a page
navigation, and the header button reopening it from any page.

**Real Playwright coverage for the wizard (recorded 2026-11-08):** the manual
browser verification above was real but one-off — the user explicitly asked for
durable, real (not mocked) e2e coverage of the wizard specifically. New
`frontend/tests/e2e/onboarding.spec.ts`, picked up automatically by the existing
`e2e-smoke` CI job (`npx playwright test` with no path argument already runs every
spec in `tests/e2e/`, so no workflow change was needed): steps through all 4 steps
including Back, confirms dismissal survives a real page *reload* (not just in-memory
state — the actual point of persisting to `localStorage`), confirms the header's "?"
button reopens it from a completely different page, and confirms the scanning step
shows either a real configured scan root or the explicit "none configured" message,
never a blank gap. Runs against the real, fully built app (same `docker compose up`
the existing smoke test uses), not a mocked API.

**Real PHPUnit test execution (recorded 2026-11-08):** closes the one item left over
from the "po kolei" roadmap work, explicitly deferred earlier this session as "a
different risk class: executes scanned code, not just reads it." The user confirmed
two scoping decisions up front via `AskUserQuestion` before any code was written:
solid sandbox hardening from day one (not a minimal v1), and Unit-only scope requiring
the module's own real `vendor/bin/phpunit`.

New `run_phpunit()` (`php-analyzer/public/index.php`) is the **first tool in this
whole sidecar that actually executes a scanned module's own code**, not just parses or
statically analyses it — every design decision below was verified empirically against
a real module (Ordo_Automation, the author's own 1500+-class, 3000+-test standalone
fixture), not assumed:

- **Scope, found the hard way:** the module's own `vendor/bin/phpunit` + its own
  `phpunit.xml`/`phpunit.xml.dist`, never a containing store's `dev/tests/unit`
  harness. Confirmed directly that the other way genuinely doesn't work: Ordo's own
  `Test/Unit/bootstrap.php` resolves `../../vendor/autoload.php` relative to its own
  root, which only exists when the module was composer-installed standalone, not when
  nested three levels deep inside a real store's `vendor/` tree (tried against the
  real Ordo module nested inside the real `magento-ordo-test/magento` store checkout —
  `Failed opening required '.../vendor/autoload.php'`). A module relying only on a
  containing store's test harness simply doesn't get this check — not a regression,
  the same kind of scope limit Ordo's own `phpunit.xml.dist` already documents for
  `Test/Integration`/`Test/Api` ("bootstrap a real, installed Magento application").
- **Coverage driver:** PCOV (`php8X-pecl-pcov`, all three side-by-side PHP versions),
  not Xdebug — lighter weight, PHPUnit auto-detects it. `pcov.directory` must match
  the module's own `phpunit.xml`'s `<source><include>` base exactly — confirmed
  empirically that a narrower directory silently produces all-zero coverage even
  though the tests genuinely ran and passed (PCOV only attributes coverage to files
  under its own configured directory).
- **Real sandboxing, not just "it's in a container":** a wall-clock `timeout -s KILL`
  (confirmed directly: correctly SIGKILLs a deliberately hung `sleep(10)` after a
  2-second test window — a memory cap alone wouldn't catch an infinite loop),
  `disable_functions` blocking every shell/process-spawning function a malicious
  test's `setUp()`/test body could call (`exec`/`shell_exec`/`system`/`passthru`/
  `proc_open`/`popen`/`pcntl_*`) — confirmed this doesn't break a real test suite
  (Ordo's own 3013 tests still pass with these disabled) — and a capped
  `memory_limit`. Independently, `php-analyzer`'s Docker Compose network membership
  changed to a new `php_analyzer_net` (`internal: true`, no internet route at all) —
  **only** this service, not the implicit `default` network every other service gets;
  `api`/`worker` stay on both, since they genuinely need internet (Packagist/GitHub/
  LLM calls) alongside reaching this sidecar. Nothing this sidecar does at runtime
  ever needed the internet to begin with (`composer install` already happened at image
  build time) — confirmed directly (`wget` to a real host failed with DNS resolution
  itself failing) that api/worker's own internet access was unaffected.
- **A real, confirmed, accepted tradeoff from that network cut, not a bug:** Ordo's
  own `PushEndpointValidatorTest::testAllowsAPublicHttpsHostname` does a genuine DNS
  lookup to verify its own SSRF-guard logic ("does this hostname resolve to a public,
  non-private IP") — which can't succeed without network access. This is the one
  known, reproducible, understood failure in Ordo's otherwise-3013-passing real suite,
  same category as `Test/Integration`/`Test/Api` being out of scope entirely: the cost
  of real network isolation for a sandbox that executes arbitrary third-party test
  code, not swallowed silently — the test asserting this behavior names the specific
  test by name rather than tolerating "at most N failures," so a genuinely new
  regression still fails loudly.
- **`ext-intl` was a real, previously-unnoticed gap:** the first real run against
  Ordo's own Test/Unit failed 4 tests with `Class "IntlDateFormatter" not found` —
  never needed by PHPStan/PHPMD/phpcs/Rector/PhpMetrics before, but a real module's
  real test code commonly exercises `Magento\Framework\Stdlib\DateTime\
  TimezoneInterface`. Added `php8X-intl` alongside `php8X-pecl-pcov` for all three
  side-by-side PHP versions.
- **JUnit parsed by counting every `<testcase>` leaf directly** (not aggregating any
  one `<testsuite>`'s own attributes), and **Clover's `coveredstatements` read from
  `<project><metrics>` directly** (not sibling per-file/per-package `<metrics>`
  elements via a blind `//metrics` search) — both XML shapes nest in a way that would
  double-count if summed at the wrong level.

New `Module.phpunit_tests_run`/`phpunit_tests_failed`/`phpunit_coverage_percent`
columns (`None` means "never executed," not "0 tests" — migration `0030`) and a new
`phpunit_failure` check_type, one finding per failing test. Added to
`_FILE_HASH_DEPENDENT_CHECK_TYPES` (purely a function of the module's own code, same
reasoning as every `check_php_static_analysis` finding). Own "PHPUnit test failures"
Stats tile — deliberately not folded into "Cross-module conflicts" (not a
cross-module concern) or "PHP static-analysis findings" (a different kind of signal:
pass/fail + coverage, not lint-style violations). No dedicated check for low coverage
itself — same "don't invent arbitrary thresholds" principle already applied to
PhpMetrics; `phpunit_coverage_percent` is exposed as a fact (module badge + API), not
a pass/fail judgment.

Verified at three independent levels, none mocked for the real-execution path: the
real `php-analyzer` HTTP endpoint directly (3013 tests, 0 failures, 96.99% coverage,
matching a manual CLI run of the same module exactly); the real orchestrator against
the real fixture through the test database (`tests/test_real_ordo_fixture.py`,
confirming `Module.phpunit_tests_run`/`_failed`/`_coverage_percent` persist correctly
and the one real network-isolation failure surfaces as a real `phpunit_failure`
finding); and the Python-side response-parsing/fail-open logic in isolation
(`tests/scanner/test_php_analyzer_client.py`, mocked HTTP layer, CI-safe and fast —
the real-execution test is gated behind the same `MAGEWIKI_ORDO_FIXTURE_PATH`-presence
skip every other real-Ordo test already uses, so it never runs in CI, only locally
where the real fixture exists).

**Kubernetes NetworkPolicy parity, closing the gap above (recorded 2026-11-08):** new
`php-analyzer-no-egress` `NetworkPolicy` (`k8s/base/php-analyzer.yaml`) mirrors
`docker-compose.yml`'s `php_analyzer_net` (`internal: true`) — an empty `egress: []`
under `policyTypes: [Egress]` means no egress at all for pods labeled
`app: php-analyzer`, while responses to already-established inbound connections
(api/worker calling the Service) are unaffected, same semantics as the Compose
change.

Before trusting this would do anything at all, checked whether it even could: `kind`'s
default CNI (kindnet) historically did **not** enforce `NetworkPolicy` — multiple
community reports (some as recent as mid-2026) say policies are accepted by the API
server but never actually enforced, while kindnet's own docs claim support, a direct
contradiction found by searching rather than assumed either way. Resolved
empirically, not from documentation: spun up a real, throwaway `kind` cluster (`kind
v0.33.0`, node image `v1.37.0`) with two bare pods and a deny-all-egress policy —
egress genuinely failed with the policy applied and genuinely came back once it was
removed. This kind/kindnet version does enforce it.

Verified end-to-end against the real magewiki stack on a real `kind` cluster after
that (not just the toy pods): `kubectl apply -k k8s/overlays/kind` creates the policy
cleanly; a real exec into the running `php-analyzer` pod confirmed egress is
genuinely blocked (`wget` to a real host fails with DNS resolution itself failing,
identical failure mode to the Compose-level verification); a real call from the `api`
pod to `php-analyzer`'s `/phpunit` endpoint confirmed ingress is completely
unaffected; and a real call to `/phpstan` against the committed demo-store fixture
confirmed the actual static-analysis tools still function normally under the
restriction (never needed egress to begin with). The `ext-intl`/`php8X-pecl-pcov`
Dockerfile additions already applied identically regardless of deployment target —
only this `NetworkPolicy` resource was the actual k8s-specific gap, and it's now
closed.

Also found live, doing this verification first-hand rather than just reading the
docs: the README's own Kubernetes quickstart never built or `kind load`ed the
`php-analyzer` image at all — only backend/frontend — despite `k8s/base/
php-analyzer.yaml` needing `magewiki-php-analyzer:dev` with `imagePullPolicy:
IfNotPresent`. Anyone following those steps literally would hit `ImagePullBackOff`
the moment that Deployment started. Added the missing `docker build`/`kind
load-docker-image` lines, and added `deployment/php-analyzer` to the final
`kubectl wait` line (previously only waited for api/worker/web).

**README screenshots refreshed (recorded 2026-11-08):** `docs/screenshots/*.jpg` and
the Wiki's own `images/*` were last captured 2026-11-07, before this session's
badges/checks/Stats tiles shipped — `stats.jpg` in particular was missing 3 whole
tiles (Cross-module conflicts, License risks, PHPUnit test failures), exactly the
kind of "repo undersells what it actually does" gap a portfolio project can't afford.
Recaptured against the real, currently-scanned fleet (790 modules across 3 real
stores) for `modules.jpg`/`stats.jpg`/`graph.jpg`/`repos.png`/`module-page.jpg`/
`quality-findings.jpg`/`settings.jpg`, plus a new onboarding-wizard screenshot
replacing the old bare-input-box `scan-box.png`. `chat.jpg` deliberately left
unchanged: recapturing it hit the real monthly LLM budget cap mid-session — the
budget guardrail correctly doing its job, not a reason to spend more real API budget
on a screenshot refresh. Two format fixes found while processing: `repos.png` and
`scan-box.png` were already actual JPEG content saved under a `.png` extension before
this session touched them — re-encoded both to genuine PNG rather than perpetuating
the mismatch.

**Agent SQL tool for quality findings (recorded 2026-11-08):** a real gap surfaced by
a full-project survey asked for explicitly to find "what's next" ideas: `list_modules`
(the one tool CLAUDE.md's own routing table already designates for "Show all payment
modules"/"how many X" enumeration questions, since top-k search can't guarantee
completeness) had no way to filter by `check_type` at all — with 18 check types now
existing (5 added just this session), nothing let a chat user ask "which modules have
a known CVE?" or "show modules with failing PHPUnit tests" despite the data already
being fully queryable. Added a `check_type` parameter (a plain `Module.id IN
(subquery)` filter, not a join — a module can have several findings of the same
check_type, which a join would duplicate into repeated rows) plus a per-module
`finding_count` in the response, present only when `check_type` is set. The tool
schema's own description lists all 18 valid values directly (no canonical Python-side
list existed anywhere to reuse — the authoritative list lives only in the
`CheckConstraint` text) so the model knows which strings to pass without guessing.
`app/agent/prompt.py`'s "how to pick tools" routing guidance updated to explicitly
steer this question class to `list_modules(check_type=...)` rather than
`search_modules` — quality findings were never indexed for semantic search, and
completeness matters here exactly the way it already does for counting questions.

**`tini` as `php-analyzer`'s PID 1 (recorded 2026-11-08):** the same project survey's
second recommendation — `php -S` ran directly as PID 1, with no init process to reap
children, exactly the failure mode `docs/v1-port-roadmap.md`'s own "operational
lessons" section already names from v1's real production history (~7000 accumulated
zombie processes on staging, fixed there with `tini`). More relevant here than when
that note was first written: `run_phpunit()` now spawns real subprocesses under a
`timeout -s KILL` wrapper specifically *because* it's the one tool in this sidecar
that executes third-party test code — exactly the kind of kill-happy subprocess
pattern that caused v1's incident in the first place. Added `tini` to the Dockerfile's
`apk add` line and switched to `ENTRYPOINT ["tini", "--"]` / `CMD ["php", "-S", ...]`.
Verified directly, not assumed from precedent: a real `ps aux` inside the rebuilt
container confirms `tini` is genuinely PID 1 with `php -S` as its child, and
triggering a real `timeout -s KILL` against a deliberately hung `sleep(30)` process
inside the running container left zero zombie (`<defunct>`) processes behind
afterward.

## Working method

- Start each phase in plan mode; propose a plan and wait for approval before writing code.
- Require tests alongside code (fixture: a small module under `backend/tests/fixtures/`).
- Reset context between phases.
- Record new decisions in this file as they're made.
- Repo language is English: README, docs, comments, commit messages, UI.
- The repo is public from day one: no secrets, no client-confidential code, ever, in commit history.

## License

MIT.
