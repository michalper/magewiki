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

## Working method

- Start each phase in plan mode; propose a plan and wait for approval before writing code.
- Require tests alongside code (fixture: a small module under `backend/tests/fixtures/`).
- Reset context between phases.
- Record new decisions in this file as they're made.
- Repo language is English: README, docs, comments, commit messages, UI.
- The repo is public from day one: no secrets, no client-confidential code, ever, in commit history.

## License

MIT.
