---
name: project-decision-log
description: Historical decision log for MageWiki-AI — dated architecture decisions, bug fixes, and incident post-mortems with verified rationale, moved out of CLAUDE.md to keep it small. Load when asked why something works a certain way, when investigating a regression that might be a known incident, or before recording a new decision here.
---

# MageWiki-AI — decision log

Dated entries recording *why* things in MageWiki-AI are implemented the way they are — incident write-ups, bug fixes, and narrower per-feature rationale. The settled, always-relevant rules live in the project's root `CLAUDE.md`; this file is the detailed history behind them, split out so it doesn't load into every session.

Keep adding new dated `(recorded YYYY-MM-DD)` entries here, grouped under the section they relate to, the same way the existing entries are.

## Architecture and stack (settled) — decisions and incidents

**Phase 3 deviation (recorded 2026-11-05):** Phase 3's AI analysis (`analyze_file` / `synthesize_module`) is implemented and verified against **Anthropic Claude** rather than DeepSeek, because real Anthropic API billing was available for genuine end-to-end verification this phase (model configured via `LLM_MODEL` in `.env`, default `anthropic/claude-haiku-5-5` — verify the exact LiteLLM model string empirically against the installed `litellm` package, the same discipline already used for `tree-sitter-php` and `arq`/`pytest-asyncio` in earlier phases). LiteLLM itself remains the abstraction layer — only the configured provider/model changed. DeepSeek and Ollama remain the stated production default per the `LLM` row above and stay wired as dormant BYOK options (`DEEPSEEK_API_KEY`, `OLLAMA_BASE_URL` in `.env.example`); switching back is a config change, not a code change.

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

## Scan, cron, and cost control — decisions and incidents

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

## RAG and the agent — decisions and incidents

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

**LLM-based reranking, opt-in (recorded 2026-11-09):** closes the "reranking...
stay deferred" item right above, once the cost decision was actually made. New
`RERANK_ENABLED` setting (`.env`, default `false` — enabling it is a
deliberate operator choice against `LLM_MONTHLY_BUDGET_USD`, not a silent
per-query cost increase). Built as a second LLM call through the same
LiteLLM/BYOK path every other call in this app already uses, not a dedicated
cross-encoder model — the latter would mean either a new heavyweight ML
dependency (sentence-transformers) or a new vendor (a hosted rerank API),
both against this project's own stated minimalism. `app/search/rerank.py`'s
`rerank_results()` is purely best-effort: it checks `is_budget_exceeded()`
itself before spending anything (independent of the chat loop's own budget
checks, since this is an extra call beyond what the loop already accounts
for), and falls back to the hybrid retriever's untouched order on *any*
failure — a provider error, no tool call, malformed JSON — because a
reranker that silently breaks search is a worse failure mode than one that's
occasionally a no-op. A hallucinated chunk id the model invents is dropped;
a real candidate it forgot to mention keeps its place, appended after
whatever it did rank, rather than either silently disappearing or corrupting
the result. `search_modules` (`app/agent/tools.py`) asks `hybrid_search` for
a wider candidate pool (20) than the caller's requested `limit` when
reranking is on — reranking a list already trimmed to the final size would
have nothing real to reorder. Rerank cost shares the same `analysis_cache`
ledger as every other LLM call (new `kind='rerank'`, migration `0032`) so it
counts toward the monthly budget the same way, and reuses the `llm_calls_total`/
`llm_call_cost_usd` Prometheus metrics (`call_type="rerank"`) the observability
work above already wired in — built two sessions apart, but the metrics
module was designed generically enough that adding a new cost center needed
zero changes there.

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

## Test data — decisions and incidents

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

## Phase plan — decisions and incidents

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
Originally a flat `components` list with no `dependencies` graph section (CycloneDX
allows omitting it) — the existing per-module dependency graph already answered "what
does X depend on"; this just answered "what's actually installed," which didn't need
the edges. Revisited once actually asked for (recorded 2026-11-08, same session as the
license-risk-prefixes and composer scripts/autoload/allow-plugins follow-ups): each
module's own direct, production (non-dev) `composer_package_requirements` rows (already
parsed for the CVE/abandoned-dependency checks) now become versionless "library"
components plus a real CycloneDX `dependencies` section — deliberately one level deep,
since this project parses a package's name and never installs it, so it has no way to
know that package's own further dependencies; "transitive" here means "what a scanned
module requires," not a fully resolved multi-level tree. Omitting the new optional
`requirements` parameter reproduces the original graph-less SBOM exactly. `license`
entries use CycloneDX's free-text `license.name` field, never
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

**Closed 2026-11-12** — see the "CI check for stale api-types.ts" part of that
day's feature-search round entry near the end of this file: `ci.yml`'s `e2e-smoke`
job now runs `npm run gen:types && git diff --exit-code lib/api-types.ts` against
its own already-live `api` container, so this exact class of silent breakage can't
recur unnoticed.

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

### Backlog: porting ideas from v1 — decisions and incidents

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

**SonarCloud follow-up triage, and why the noise can't be silenced from a committed
file (recorded 2026-11-08):** after the first SonarCloud pass (commit fixing
`pythonsecurity:S5145` and the regex-alternation rules, same day), the author asked
directly to stop the remaining alerts from "showing up in the configuration" — a
second full pass over all 214 still-open issues, grouped by rule this time rather
than read one-by-one. Found and fixed six more genuinely real/cheap ones: an unused
`chunks_by_path` parameter on `_run_scenario()` (`app/evaluation/run_ci_eval.py`,
dead since `main()` already resolves it before calling in); two `# noqa: BLE001 -
<reason>` comments (`health.py`, `agent/loop.py`) reformatted to put the reason on
its own line, since ruff's dialect tolerates trailing text after a noqa code but
SonarCloud's own suppression-comment-format rule (`python:S7632`) doesn't; a
redundant `list(edges)` in `circular_dependencies.py` (verified `edges` is never
mutated during that loop — `visit()` only ever touches `color`/`path`/`cycles`, so
the defensive copy was never load-bearing); the onboarding-wizard context's `value`
prop being a fresh object+closure every render (`useMemo`/`useCallback` now memoize
it); and two accessibility fixes on the dependency-graph page
(`GraphClient.tsx`) — the connector `<svg>` marked `aria-hidden` (decorative; labels
are separate HTML nodes overlaid on top), and a clickable node switched from a
`role="button"` `div` with manual `onKeyDown` to a real `<button>` (native Enter/
Space activation, confirmed by the existing keydown test still passing unchanged).
Also added `void` to the one genuine fire-and-forget `startScan()` call
(`modules/page.tsx`) and hoisted `clearQueryParam` out of the component (pure
function, no closure over component state) per two more real, trivial findings.
`ci.yml`'s `pull-requests: write` was scoped from workflow-level down to just the
one job that actually posts a PR comment (`rag-eval-comment`), since nothing else
needs it. All verified against the full backend pytest run, ruff, mypy, frontend
lint/typecheck, and `vitest run --coverage` (100% lines/statements/functions
unchanged) before committing.

The rest (python:S3776 cognitive complexity on fleet-wide scanner functions,
typescript:S6759 read-only props, CI/Docker hardening boilerplate, generated-file
naming, ARQ's required-but-unused `ctx` job parameter, test-style nits, etc.) is the
same category of accepted noise the first pass already reasoned through — nothing
new, just more of it once grouped by rule instead of read one issue at a time.

Important constraint discovered this pass: **this project's SonarCloud analysis runs
in "Automatic Analysis" mode** (the SonarCloud GitHub App scans on every push; no
`SONAR_TOKEN` secret exists in the repo, confirmed via `gh secret list`, and `ci.yml`
has no sonar-scanner step). A committed `sonar-project.properties` with
`sonar.issue.ignore.multicriteria` — the normal way to silence a rule/path
combination from version control — is **not read at all** in that mode; it only
takes effect under CI-based analysis (a real `sonar-scanner` step authenticated with
a token). Writing one anyway would have looked like a fix while doing nothing, so it
wasn't committed. Silencing the remaining accepted-noise issues for good requires
one of: (a) the author bulk-resolving them as "Won't Fix"/"False Positive" on
SonarCloud's own Issues page (a few clicks per rule, filtering by rule key — free on
the public-repo tier, no token needed), or (b) generating a SonarCloud token and
adding it as this repo's `SONAR_TOKEN` secret, which would let a future session wire
up real CI-based analysis with a committed, version-controlled properties file —
worth doing only if (a) turns out to be too tedious to repeat as new noise
accumulates.

**Update, same day:** the author picked (b). Wiring it up surfaced two real CI
problems, both fixed: (1) a brand-new `SONAR_TOKEN` (generated as a *Project
Analysis Token*) got a 403 from every `api.sonarcloud.io` endpoint the scanner
calls, including generic bootstrap ones (`/analysis/jres`, `/analysis/engine`) —
not a scope issue on one endpoint, the token just wasn't accepted at all;
regenerating it as a plain *User Token* fixed every call. Also had to turn off
the SonarCloud project's own "Automatic Analysis" toggle (Administration →
Analysis Method) — confirmed via the project's own settings page it was still
on — since SonarCloud explicitly documents the two analysis methods as
mutually exclusive, though in this case it turned out not to be the actual
cause of the 403 (the token was). (2) A `SONAR_SCANNER_SKIP_JRE_PROVISIONING`
workaround tried mid-diagnosis to isolate the 403 became actively harmful once
the token was fixed — it forced the scanner onto `ubuntu-latest`'s preinstalled
Java 17, and this scanner version requires Java 21+; reverted once the real
fix (new token) landed and auto-provisioning could do its job again. Final
result verified against the real, public SonarCloud API: 214 open issues → 5,
all five read directly (not assumed) and genuinely false positives (`array.sort()`
on plain string enums; ReactMarkdown's `h1`/`h2`/`h3` overrides carrying their
real content through a `{...props}` spread Sonar's static check can't see
through) — added to `sonar-project.properties` as e44/e45 rather than left
open.

**Observability: structured request logging + Prometheus metrics (recorded
2026-11-09):** the app had none at all -- no per-request correlation in logs,
no metrics beyond what Codecov reports about test coverage. New
`app/observability.py` threads a per-request id (`X-Request-ID`, generated if
the caller doesn't send one) through every log line via a `logging.Filter`
reading a `contextvar`, and exposes `GET /metrics` (Prometheus text format):
HTTP request count/duration labeled by the route's own path template (not the
raw URL, so a module id in the path doesn't create one series per module);
`llm_calls_total`/`llm_call_cost_usd` labeled by model + call_type
(completion/embedding/chat), hooked into the one real shared choke point each
cost center already funnels through (`analyzer/client.py`'s
`_result_from_response`, `embeddings.py`'s `embed_text`, `agent/loop.py`'s
`_turn_cost`) rather than scattered at every call site; `llm_monthly_spend_usd`,
a DB-backed gauge set at scrape time from the same query `budget.py`'s
`is_budget_exceeded()` already runs (extracted into a shared
`get_monthly_spend_usd()` helper both now call); and `scan_duration_seconds`,
hooked into `_scan_response()` (shared by `/scan` and `/scan/stream`).

Found and fixed two pre-existing coverage gaps while verifying this against a
clean, single-invocation full suite run (the project's own 100%-coverage gate
never actually enforces via `pytest`/`--cov-fail-under` — it's enforced via
Codecov's project+patch targets, so a tiny, real gap like this could have sat
unnoticed): `composer_conflicts.py`'s self-pair skip inside the pairwise loop
was real and reachable (a module requiring the same package twice) but
untested — the existing "same module twice" test had only one other distinct
module_id, so the outer "fewer than 2 distinct requirers" guard returned
before the pairwise loop was ever reached; added a three-row test that
actually forces it. `circular_dependencies.py`'s analogous guard is,
after working through the proof, mathematically unreachable given how
`edges`/`name_to_id` are built from the same loop over the same rows — marked
`pragma: no cover` with the reasoning inline rather than writing a misleading
test to force it.

Verified against the real, **rebuilt** (not just bind-mounted) `api`/`worker`
images, which surfaced an unrelated, pre-existing operational gotcha: the
`migrate` one-shot service has its own separate image (same Dockerfile/context
as `api`/`worker`, but no `image:` key shared between them, so Compose builds
three independent images) with no bind mount, and it turned out to be stale
from well before migration `0031` ever existed — `docker compose build api
worker` didn't rebuild it, since it's a genuinely separate image. `docker
compose up -d api worker` failed with "Can't locate revision identified by
'0031'" until `migrate` was rebuilt explicitly too. Not caused by this
session's changes (nothing here touched migrations), only surfaced because
this was the first non-bind-mounted full rebuild in a while — `api`/`worker`
normally hot-reload via their bind mount and never need rebuilding, so
`migrate`'s own staleness had no way to show up until something finally
forced a real `docker compose up` through it again. After the fix: `/health`
reports `schema: "ok"` at revision `0031`, `/metrics` returns real Prometheus
text including a real `llm_monthly_spend_usd` value from the live DB, and
`filelock` is confirmed at the CVE-fixed `4.2.9` (the Dockerfile's own
post-`poetry install` override, re-verified still correct after rebuild).

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

**Real e2e coverage for every page, not just onboarding (recorded 2026-11-09):**
before this, `tests/e2e/` had exactly two specs: the onboarding wizard and a
single boot-smoke check on the Modules page with zero scanned data --
everything else (Modules filtering/sorting/CSV, the module detail page, the
dependency graph, Chat, Stats, Repos/SBOM, Settings/BYOK) had unit-test
coverage for component logic but no real browser-driven user-journey test at
all. "100% coverage" in CI has only ever meant unit-test line coverage
(pytest/vitest); it never implied e2e journeys were covered too, and nothing
made that distinction explicit until a user asked directly.

The real blocker turned out to be infrastructure, not test-writing:
`e2e-smoke`'s `.env` (copied from `.env.example`) had no `MAGEWIKI_SCAN_ROOT_*`
configured at all, so `is_within_scan_roots()` failed closed and **no e2e test
could ever trigger a real scan through the UI** -- every page beyond the bare
Modules shell was permanently untestable with real data. Fixed by pointing
`MAGEWIKI_SCAN_ROOT_1` at the already-committed `backend/tests/fixtures/demo-store`
fixture in `ci.yml`'s `e2e-smoke` job -- parser-only findings (no AI, no LLM
key needed), so it scans successfully even with every `*_API_KEY` left empty,
which is deliberately the case for this whole job (no real LLM spend in CI).
New `tests/e2e/global-setup.ts` seeds that one scan directly via the API
(not through the UI) once, before any test file runs -- `fullyParallel: true`
gives spec files no guaranteed order, so a per-file scan would race two
`POST /scan` calls against the same repo_root into a `ScanAlreadyInProgressError`.
`modules.spec.ts` still has its own dedicated test driving the actual Scan
button/progress UI (a cheap, hash-skipped rescan of the same fixture).

Every new spec's assertions are against the *real*, verified behavior of this
specific environment (no API key configured), confirmed by actually driving
a real isolated stack in a browser before writing a single assertion, not
guessed from reading component source: a module can never reach `up_to_date`
here, so "This module has not been analyzed yet." is the one deterministic
README state to assert on (not a transient loading state that would make the
test flaky); sending a chat message deterministically resolves to the
agent's own real graceful-failure path ("chat failed unexpectedly — check
server logs"), not a generated answer -- asserting on that reproduced real
behavior is more meaningful than mocking a fake one would be.

Found and fixed real bugs this surfaced, not just wrote new tests around:
(1) Two `getByRole("button", { name: "Scan" })`/`{ name: "Dev" }` locators
(one in the **pre-existing** `smoke.spec.ts`, never caught before because the
Modules page never had real scanned data to render a "Last scanned" sortable
column header against) were ambiguous substring matches -- Playwright's
default name matching is substring, and "Scan" matches "Last scanned" the
same way "Dev" matches Next.js's own dev-mode-only "Open Next.js Dev Tools"
button; both needed `exact: true`. (2) Two Settings tests that each mutate
the same backend singleton (`RuntimeLlmConfig`, id=1) raced each other under
`fullyParallel: true` -- which parallelizes tests *within* one file too, not
just across files -- confirmed directly (passed reliably alone, failed
intermittently together) and fixed with `test.describe.serial()`. Neither of
these would have been caught by code review; both needed a real multi-run
local verification pass (a throwaway, fully isolated `docker compose -p
magewiki-e2e` stack on separate ports with its own `.env` -- `env_file: .env`
in `docker-compose.yml` is a literal relative path, so `--env-file` alone
doesn't override what containers actually read; needed an override compose
file pointing `env_file` at the isolated `.env` too) before trusting any of
this enough to push.

**Four more real e2e gaps closed, after an honest self-audit (recorded
2026-11-09):** asked directly whether e2e coverage above was actually
complete; it wasn't — the first pass covered the happy path per page, not
error states. Added, each verified live in a real browser before writing the
assertion: (1) scanning an out-of-scan-roots path shows the real UI text
("API responded with 400") -- `_validate_scan_path` rejects it with a 400
*before* the SSE stream ever starts, and `streamSse` (`lib/sse.ts`) throws a
generic "API responded with `<status>`" for a non-ok response rather than
surfacing the backend's real `detail` text; this asserts on the actual,
current behavior, not the more informative message a reader of the backend
code alone would assume is shown. (2) the scan log panel shows a real,
specific line ("Found 1 modules, scanning..."), not just the final result
text, extending the existing real-scan test. (3) a nonexistent module id
(`/modules/999999999`) shows "Failed to load module." instead of hanging --
this surfaced a real, if minor, latency gap while verifying live: the
QueryClient has no custom retry config, so TanStack Query's own default (3
retries, exponential backoff: 1s/2s/4s) genuinely delays the error state by
~8s even though the 404 can never succeed on retry; the test's timeout was
raised to 15s to match the real, confirmed delay rather than treating it as
flake. (4) a Stats KPI tile's info-tooltip reveals its real description text
on hover (Base UI tooltip, confirmed the 300ms open delay doesn't need any
special handling — Playwright's own `expect().toBeVisible()` retry already
covers it).

Explicitly deferred, not forgotten: the Settings re-embed-confirmation flow
(needs a module in `up_to_date` state, which requires a real LLM key this
CI job deliberately never has); multi-store-scan/cross-module-conflict/
license-risk UI states (the single-module demo-store fixture structurally
can't produce them without either a real API key or enriching a long-stable,
widely-depended-on fixture — not done without a clearer need); dependency
graph node-to-node navigation (same fixture limitation -- the fixture's only
non-center graph node, Magento_Sales, is an external/unscanned reference,
not a real second module to navigate to); and the mobile card view (CSS
`md:hidden` only hides `ModuleCard` visually at desktop viewport -- it still
mounts and renders in the DOM regardless of viewport, so its logic is
already indirectly exercised by the existing desktop-viewport tests; a
dedicated narrow-viewport run would mainly confirm visual layout, lower
marginal value for the effort than the four gaps actually closed).

**Real backend bug found while e2e-testing the Settings page's embedding
flows (recorded 2026-11-09):** closing "is anything still missing?" surfaced
three more untested real flows (the enabled-status filter dropdown, CSV
export content, and the Embeddings section of Settings) -- the last one hit
a genuine, confirmed backend bug, not just a coverage gap. `PATCH
/settings/llm` ran its live embedding-dimension probe (`embed_text`,
"Configurable embedding dimension" decision above) whenever `embedding_model`
was merely *present* in the request body, not only when the *effective*
model was actually changing. Verified live against the real, no-embedding-
key isolated stack: clicking Settings' own "Reset to .env default" for
Embeddings -- a genuine no-op, since there was no override to clear --
still made a real `embed_text` call and failed outright with a 400
("Missing credentials..."), with no feedback path for an operator to
recover from it other than editing `.env` directly. Fixed by moving the
`effective.model != old_embedding_model` check (already used further down
to gate the `confirm_reembed` decision) to guard the probe itself, so a
genuine no-op never calls out to a real provider at all. Two existing tests
(`test_patch_embedding_model_with_matching_dimension_succeeds`,
`test_patch_embedding_model_surfaces_a_probe_failure_as_400`) had
accidentally been asserting against `settings.embedding_model`'s own
already-effective default as their "new" value, so they still passed their
literal assertions after the fix but silently stopped exercising the probe
path they were named for -- fixed to use a genuinely different model
(`ollama/bge-m3`), with an explicit `probe_called` flag added to catch this
category of drift again. New `test_patch_embedding_model_skips_the_probe_
entirely_when_unchanged` is the direct regression test. Two new e2e specs
(`settings.spec.ts`) assert on the real, now-correct behavior: Reset
succeeds silently, and a genuinely new model still shows the real probe
error (no embedding key is configured anywhere in this CI path, so that
failure mode stays real and deterministic, not mocked away).

**Five more real e2e gaps closed on a third audit pass (recorded
2026-11-09):** asked again ("szukaj kolejnych luk") after the embedding-
settings bug fix above. Added, each checked against the fixture's real
composer.json/API response first, not assumed: composer facts never
asserted on before (`License` → "MIT, OSL-3.0", `Autoload (PSR-4)` →
"Vendor\Module\ → .", `Depends on` → "Magento_Sales" -- confirmed via a
direct `GET /modules/{id}` call against the real seeded module, not guessed
from reading the component alone); the Stats page's three percentage tiles
(Have a README / Have tests / Have an AI-generated doc), real and
deterministic 0% for all three since the fixture module has none of those;
and, on the Repos page, the README/tests count columns and -- a genuinely
new interaction, not just a new assertion -- clicking a repo card itself
navigates to a repo-filtered `/modules?repo=...` view (the whole card is a
`<Link>`; "Download SBOM" is a nested button with its own
`stopPropagation`, previously the only thing ever clicked on that card).

Two real test-authoring pitfalls surfaced and fixed while verifying this
live, both about over-broad text matching, not app bugs: (1) the repo
card's own accessible name is its *entire* concatenated text content (module
count, every stat, every quality badge, the nested button) since the whole
card is one `<Link>` -- matched by its real `href` attribute instead of
`getByRole("link", {name: ...})`. (2) the repo_root path string legitimately
renders in more than one place on the post-navigation Modules page (the
"Filtering by repo:" banner *and* the always-visible "Scannable under:" scan
helper text) -- a bare page-wide `getByText(repoRoot, {exact: true})`
strict-mode-violated; scoped to the banner's own container instead.

Also self-inflicted, caught and fixed before it reached a commit: reusing
the local isolated verification stack's Postgres volume across two rebuilds
(a `docker compose down` without `-v`, to free resources while a slow
backend test run was in progress) left a stale repo_root row in the DB from
an earlier run, which happened to have been scanned under a different
case-variant of this machine's own working-directory path
(`/Users/.../Projects/magewiki` vs `/Users/.../projects/magewiki` -- macOS's
case-insensitive-but-preserving filesystem lets both resolve, and different
shell invocations in this long session surfaced different casing) --
produced two rows for what was semantically the same fixture and broke an
exact-count assertion. Not a real bug in the app (repo_root is correctly
treated as a case-sensitive string key throughout); fixed by always tearing
the isolated stack down with `-v` for a genuinely clean slate rather than
reusing a volume across rebuilds.

**Two more real SonarCloud findings fixed (recorded 2026-11-09):** checked
the project's SonarCloud issues page again after the earlier triage passes
left it at 5 accepted false positives — two new, real, open findings had
appeared since then (`python:S8414` BLOCKER on `backend/app/main.py:19`,
`python:S5958` MAJOR on `backend/tests/evaluation/test_faithfulness.py:164`),
both verified against the real code before fixing, not assumed from the
rule description alone. (1) `create_app()` added `CORSMiddleware` before
`RequestIdMiddleware` — Starlette makes the *last*-added middleware the
*outermost* layer, so `RequestIdMiddleware` was wrapping `CORSMiddleware`,
not the other way around. If `RequestIdMiddleware` (or anything added after
it) ever raised before reaching `CORSMiddleware`, the response would reach
the browser with no CORS headers at all — the browser reports an opaque CORS
error instead of the real failure, which would make a real production
problem much harder to diagnose from the frontend. Fixed by swapping the
order so `CORSMiddleware` is added last. (2) A `pytest.raises(Exception)` in
`test_faithfulness.py` already had a `# noqa: B017` explaining the broad
catch was deliberate ("any pydantic ValidationError shape is fine here") —
but checked what `judge_faithfulness` actually raises
(`FaithfulnessVerdict.model_validate(data)`, a Pydantic model) and narrowed
the assertion to the real `pydantic.ValidationError` instead, which closes
the Sonar finding by actually testing the real failure mode rather than by
suppressing the rule. Verified both against the real stack, not just unit
tests: rebuilt `api`/`worker` (and the separately-built `migrate` image,
which had again gone stale per the "Advisory-lock"/observability notes
above — same recurring gotcha), confirmed `/health` reports `schema: "ok"`
at the new revision, and confirmed a real `curl` with an `Origin` header
still gets back a correct `access-control-allow-origin` response header
after the middleware reorder.

**Phase 15: cross-module conflict detection, round 2 (recorded 2026-11-09):**
closes a research pass on what was genuinely still missing (everything
through Phase 14 was done; Phase 13 is blocked on cloud budget, not a
feature gap). Three more checks, same fleet-wide Phase-C pattern and
`module_quality_findings` table as the existing plugin/composer/webapi/
db_schema/circular-dependency family: `preference_conflict` (two modules
declaring a different `di.xml` `<preference>` for the same interface — the
losing module's implementation is silently never used, not a documented
override mechanism the way `<plugin>` sortOrder is), `cron_job_conflict`
(two modules declaring a `crontab.xml` job with the same job code but a
different instance/method — Magento merges by job code, so the loser's job
silently never runs), and `graphql_field_conflict` (two modules declaring
the same field on the same GraphQL type with different resolvers). All
three reuse data already parsed since Phase 1 (`di_preferences`) and Phase
14 (`cron_jobs`, `graphql_fields`) — new detection logic only, no new
scanning risk. New check_types via migration `0033`.

While adding the migration, found and fixed a real but harmless drift:
`app/models.py`'s own `ModuleQualityFinding.CheckConstraint` text hadn't
been updated since roughly migration `0012` (every check_type added by
migrations `0022` through `0030` — `plugin_conflict` through
`phpunit_failure` — was missing from it), even though every one of those
migrations correctly updated the real constraint via `op.create_check_constraint`.
Harmless in practice (confirmed: `tests/conftest.py` always runs a real
`alembic upgrade head` against a fresh test DB, never
`Base.metadata.create_all()`, so the real schema never came from this
text), but misleading to a future reader — synced it to the full, real
cumulative list as part of this migration.

Verification note: a long run of this session's own pytest invocations
repeatedly overlapped (each one 5-17 minutes against the same shared test
Postgres/Redis/php-analyzer, started before confirming the previous one had
actually finished) and produced a long tail of confusing, cascading
failures — `ScanAlreadyInProgressError`, `StaleDataError: 0 rows matched`,
`PendingRollbackError`/"connection is closed", and `php-analyzer` 400s —
all classic concurrent-test-run symptoms (advisory lock contention, two
processes racing the same fixture rows, the single-threaded `php -S`
sidecar saturated). None of these ever landed in this phase's own new
files across any run; the one genuinely clean, fully isolated run (checked
via `ps aux` before starting, confirming zero other pytest processes) had
all 23 of this phase's own tests (6 unit + 6 orchestrator... plus the
no-conflict negative cases) pass cleanly, and `ruff`/`mypy` were clean
throughout. Lesson for next time: confirm a previous background pytest
invocation's own completion marker (not just a point-in-time `ps aux`) before
starting another, and prefer `tests/scanner` (or narrower) over the full
~10-17 minute suite when re-verifying a scoped change.

**sonar.tests broke the CI sonar job outright (recorded 2026-11-09):** the
`sonar.tests` fix for the Python-only analysis warning (above) was itself
broken -- added `frontend/**/*.test.ts,frontend/**/*.test.tsx` alongside
the two real directories, and SonarCloud's scanner doesn't accept
wildcards in `sonar.tests`/`sonar.sources` at all ("Invalid value of
sonar.tests... Wildcards ** and * are not supported"), failing the whole
job with no analysis run. Caught via a real CI run, not predicted.
Frontend's own tests are co-located (`*.test.tsx` next to the component it
tests, scattered across `app/`, `components/`, `lib/`) with no dedicated
test directory other than `frontend/tests` (the Playwright e2e specs) --
there's no clean way to mark them via `sonar.tests` without also
mis-marking their sibling production files as tests, so narrowed back to
just `backend/tests,frontend/tests` and accepted that the co-located files
stay unclassified. Verified against a real run after the fix: `sonar` job
green in 56s.

**Phase 16: module history (recorded 2026-11-09):** closes the roadmap's
third item alongside Phase 15 and the (still-pending) RAG query rewriting.
New `module_history_snapshots` table -- one row per module per *change*
(hash/state/enabled/finding_counts), not per scan, written in
`orchestrator.py` right after Phase C's cross-module conflict detection
(a module's finding_counts aren't complete until conflicts involving it
are persisted). Dedup at write time (`app/scanner/history.py`'s
`snapshot_changed()`) is the load-bearing guard against the exact
unbounded-growth failure this file's own "Operational lessons" section
already names from v1's real production history (an insert-only history
table that grew to 3.7GB before a manual cleanup) -- discussed directly
with the user before writing any code ("a nie zajedzie nam to bazy?"),
with concrete worst-case numbers (~190MB/year even if every one of 750
modules changed every single day, which doesn't happen in practice) and a
second line of defense: a new nightly `prune_module_history` cron
(`worker.py`) deleting snapshots older than a year except each module's
own oldest row, kept forever as a baseline. New `GET /modules/{id}/history`
endpoint (newest first). Frontend: a "History" card on the module detail
page, diffing each entry against the next-older one client-side (nothing
server-side needed to diff consecutive entries, since each already carries
its own full `finding_counts`) -- hash/state/enabled changes plus
per-check-type finding-count deltas with ▲/▼. Scoped to module-level only,
not a repo-level aggregate, as a deliberate cut to avoid scope creep.
Verified: 15 new backend tests + the full `tests/scanner` suite (314
tests) passing in one clean, isolated run; frontend 100% lines/statements/
functions on the changed file (96.38% branches, consistent with this
project's own already-established branch-coverage tolerance).

**Phase 17: RAG query rewriting, opt-in (recorded 2026-11-09):** closes the
RAG section's own "post-1.0" wishlist (retrieval-debugging panel and
reranking were already done; this was the one remaining item, deferred
pending its own independent per-query LLM cost decision, same as reranking
had been). Built by mirroring `app/search/rerank.py`'s shape as closely as
possible: a new `QUERY_REWRITE_ENABLED` setting (default `false`,
independent of `RERANK_ENABLED` — each flag gates its own cost
decision), `app/search/query_rewrite.py`'s `rewrite_query()` is best-effort
(checks `is_budget_exceeded()` itself, falls back to the original query on
any failure -- budget, provider error, missing tool call, empty rewrite --
rather than ever risking retrieval running against something the user
didn't actually ask for), and cost shares the same `analysis_cache`
ledger (new `kind='query_rewrite'`, migration `0035`) and
`LLM_CALLS_TOTAL`/`LLM_CALL_COST_USD` Prometheus metrics every other cost
center in this app already goes through.

`search_modules` (`app/agent/tools.py`) runs the rewrite first when
enabled, then feeds its own output into `hybrid_search` and, if also
enabled, into reranking -- each stage consumes the previous stage's best
output rather than every stage re-reading the raw user string. Also
synced `AnalysisCache`'s own `CheckConstraint` text in `models.py` (same
drift class as `ModuleQualityFinding`'s fixed in Phase 15 -- it had
already drifted once before, missing `'rerank'`, confirming this is a
recurring pattern worth watching for on every future `kind`/`check_type`
addition). `docs/architecture.md` and `CLAUDE.md`'s RAG section both
updated to reflect the wishlist is now fully closed, not just reranking.

Verified: 42 new/changed tests (`tests/search/test_query_rewrite.py` +
two new wiring tests in `tests/agent/test_tools.py`) plus a full
656/657-passing backend suite run (the one failure,
`test_real_ordo_automation_phpunit_execution`, was residual `php-analyzer`
degradation from this same session's earlier concurrent-pytest chaos during
Phase 15 -- confirmed by restarting the sidecar and re-running just that
one test, which then passed cleanly; it's also gated behind
`MAGEWIKI_ORDO_FIXTURE_PATH` and never runs in CI regardless). `ruff`/`mypy`
clean throughout. This closes the three-item roadmap (Phases 15-17) added
earlier this session from a "what's genuinely still missing" research
pass.

**Security tab triage: 199 Trivy alerts + 5 missed CodeQL false positives
actually dismissed, not just reasoned about (recorded 2026-11-09):** a
real-world test of this project's own CLAUDE.md -- a user asked to verify
the Security tab, which showed 201 open alerts even though the "Code-
scanning/Dependabot alert triage" and "SonarCloud follow-up triage" notes
above already claimed this category (base-image OS-layer CVEs, not app
dependencies) was handled. Checking GitHub directly showed otherwise: only
1 Trivy alert had ever actually been dismissed, and 5 `py/path-injection`
CodeQL alerts from the original security-review pass were still open too.
The *reasoning* was sound and already correct (verified again here by
sampling real package names across the 199: `libc6`, `virtualenv`,
`coreutils`, `mount`, `login`, `libsqlite3-0` -- genuinely Debian
base-image packages pulled in by `python:3.13-slim`, not anything this
project's own `pyproject.toml`/`package.json` declares) -- the gap was
purely that recording a decision in CLAUDE.md was once mistaken for
actually executing it on GitHub. Both triaged for real this time: the 5
CodeQL alerts (confirmed downstream of `is_within_scan_roots()`, the same
already-validated sanitizer CodeQL's taint analysis can't trace) and all
199 Trivy alerts (195 backend + 4 frontend) dismissed via the Code
Scanning API with an explanatory comment each (`won't fix` /
`false positive` as appropriate). The 2 open Dependabot alerts
(`minimatch`, `deepmerge`) were deliberately left open, not dismissed --
already-reasoned as "no fix available yet, already at the newest version
within the locked major," a different category from "won't fix." Verified
directly against the real GitHub API afterward: 0 open code-scanning
alerts, exactly 2 open Dependabot alerts. Lesson: a decision recorded here
is not the same as the decision being *applied* somewhere external to this
repo (GitHub's alert state, in this case) -- worth an explicit verification
step, not just trusting a past recorded rationale, the next time this
tab is checked.

**JS/CSS bundle-size CI gate (recorded 2026-11-09):** added `size-limit`
(`@size-limit/file`), run as `npm run size` right after `npm run build` in
the frontend CI job, closing a real gap -- nothing before this caught an
accidentally-added large dependency before it shipped. Budgets set from
the real measured production build, not guessed: 550 kB for
`.next/static/chunks/**/*.js` (381.64 kB brotlied today, ~44% headroom)
and 40 kB for the CSS chunks (9.09 kB today). Next.js 16/Turbopack no
longer prints a First Load JS table to the build console the way older
webpack-based builds did, confirmed empirically (`npm run build`'s own
output has no size table at all now) -- `size-limit` measures the real
files on disk instead, which also means it doesn't depend on that console
format staying stable. Also found, while checking: Turbopack's build
output puts CSS files directly in `.next/static/chunks/` (a `.css`
extension alongside the `.js` chunks), not in a separate
`.next/static/css/` directory the way some other setups do -- confirmed
directly (`size-limit` failed outright on a first guess at the CSS path
with "can't find files") before landing on the real glob.

**Single-retry on a real Postgres deadlock persisting a module (recorded
2026-11-09):** closes the "cosmetic, not urgent" follow-up flagged right
after the real `Ordo_Automation` deadlock hit earlier this session
(`DELETE FROM file_hashes` racing a concurrent job touching the same
rows). `_is_deadlock()` checks SQLSTATE `40P01` specifically and retries
exactly once (`_MAX_MODULE_PERSIST_ATTEMPTS = 2`) -- a deadlock surviving
one immediate retry is more likely a real, persistent lock-ordering
problem than transient contention, so it's then surfaced as a genuine
module failure rather than retried forever. Non-deadlock failures are
never retried, unchanged from before.

Found and fixed a real bug while building this, not just added the
retry: the per-module `try/except` never called `session.rollback()` on
failure, relying only on the savepoint's own automatic rollback on exit
-- which doesn't fully clear a DBAPI-level error that can leave the
session's outer transaction/connection unusable for whatever runs next.
This was the actual cause of the cascading `PendingRollbackError` seen
earlier this session on the module *after* the deadlocked one, previously
misread as a second, unrelated bug. The explicit `session.rollback()`
added here is what makes the retry able to succeed at all, and it
protects every other per-module failure mode the same way, not just
deadlocks -- a module failing for any reason no longer risks corrupting
state for whatever the scan processes next.

Verified with 3 new tests simulating a real deadlock via a monkeypatched
`_persist_module` (retries once and succeeds; exhausts retries and
surfaces as a real failure; a non-deadlock error is never retried), plus
the full `tests/scanner` suite (315 tests) passing in one clean run.

**Modules-list pagination and debounced search; dependency graph switched to a
multi-hop force-directed layout (recorded 2026-11-10):** both driven by real
usage feedback from a colleague (Marcin) reviewing the live app, relayed via
chat. Three separate findings, in the order they came in:

1. **Pagination + search debounce** (`frontend/app/modules/page.tsx`): "hard
   to sort/browse" (the full filtered list rendered as one long table) and
   the search box visibly lagging on the real ~760-module fleet. Added
   client-side pagination (25/50/100/200 per page, selectable) over the
   already-fetched `filteredAndSorted` array — the architecture stays "fetch
   once, filter/sort/paginate in memory," not a new paginated `/modules` API,
   since the whole list was already being fetched and held client-side
   before this. CSV export still exports the full filtered set, not just the
   visible page. The search lag was never literally "searching the DOM" (the
   colleague's guess) — it was an un-debounced re-filter + full-table
   re-render on every keystroke; a 250ms debounce (`frontend/lib/use-
   debounced-value.ts`) fixed it. Page resets to 1 directly in each
   filter/search/page-size change handler (not a `useEffect`) — this
   session's eslint-plugin-react-hooks flags both `setState` inside a
   `useEffect` and the "adjust a ref during render" pattern the React docs
   themselves recommend for this exact "reset derived state when an input
   changes" case, so neither of the two textbook approaches is available
   here; a plain `currentPage = Math.min(page, pageCount)` clamp is the
   backstop for the cases with no handler to hook into (the URL-driven
   `repo`/`finding` query-param filters, or the list simply shrinking on
   refetch).

2. **"Is composer.json actually required for app_code modules?"** — a
   question, not a bug report, but investigated end-to-end rather than
   answered from memory since nobody had verified it this session: a
   screenshot showed a module with real `composer_completeness` warnings
   (missing `require.php`, missing `require-dev phpunit/phpunit`), prompting
   "would a *missing* composer.json show some error?" Traced the whole path,
   not just the one obvious function: `parse_composer_json()`
   (`app/scanner/composer_json.py`) returns `None` for a missing file via an
   early `is_file()` check (never raises, never hits the per-module "error"
   status path in `orchestrator.py`); every downstream consumer in
   `_persist_module` already guards with `pm.composer.X if pm.composer else
   default`; `composer_completeness_findings()` returns `[]` for `None`;
   `check_license_risk`/`check_magento_upgrade_readiness`/
   `check_security_advisories`/`check_abandoned_outdated` all degrade to
   empty inputs (`license=None`, `requirements={}`) and return `[]`. A
   module's `state` only ever becomes `"failed"` from the async AI-analysis
   worker job raising (`app/tasks/jobs.py`), never from scan-phase composer
   parsing. **Conclusion: a wholly missing composer.json already produces
   zero findings, zero exceptions, zero failed state — confirmed correct,
   no code change needed.** Recorded here specifically so a future session
   doesn't re-walk this same trace from scratch.

3. **Dependency graph: multi-hop + force-directed layout**
   (`backend/app/api/routes/modules.py`'s `get_module_dependency_graph`,
   `frontend/app/modules/[id]/graph/GraphClient.tsx`): two more pieces of
   feedback on the same page, within the same conversation — "the full name
   only shows on hover, it should always be visible" (single-line
   `truncate` on a fixed-width box), then "I'd also want to see deeper
   dependencies, a bigger graph." Fixing the label alone (wrap instead of
   truncate) was tried first and made a *pre-existing* bug worse: screenshot
   comparison on a real module (`Magento_Catalog`, 16 direct neighbors)
   showed the old fixed-radius one-ring circle layout already overlapped
   nodes near the top/bottom of the ring at that neighbor count — taller
   wrapped boxes turned a readable edge-touch into near-total overlap.
   Decided with the user (explicit choice between "force-directed" and
   "keep the ring, just fix spacing") to redo the layout with **d3-force**
   (new frontend dependency, `d3-force@3.0.1` — the force-simulation math
   only, not all of d3) rather than patch the ring math, since the ring
   approach fundamentally can't extend to multiple hops either way.
   Backend: `get_module_dependency_graph` gained a `depth` query param
   (1–3, default 1 — unchanged default behavior, existing tests pass
   unmodified) and now BFS-expands hop by hop via a `visited_module_ids`
   set (verified against a real two-module A→B→A cycle test — a naive BFS
   without this would expand forever), capped at `_MAX_GRAPH_NODES = 120`
   total nodes with a new `truncated: bool` response field (a
   highly-connected core module could otherwise balloon depth=3 into
   thousands of nodes and as many query round trips — each hop re-runs the
   same per-module relation queries, not batched across the whole frontier,
   accepted as fine at this project's scale rather than a bigger rewrite).
   Frontend: nodes collide-avoid by an *estimated* box size from label
   length (not a real DOM measurement pass — deemed not worth the
   complexity), the center module is pinned (`fx`/`fy`) at the simulation
   origin, and the simulation runs a fixed 300 ticks synchronously (no
   live animation, no `Math.random`-seeded placement) so layout stays
   deterministic for a given graph. Tuning `forceManyBody`'s
   `distanceMax` and `forceX`/`forceY` strength mattered as much as any of
   that: an untuned simulation spread even a 16-node star graph across a
   ~4000px canvas with the center node scrolled out of the default view —
   verified visually via real Playwright screenshots against the live dev
   stack (not just unit tests) both before and after tuning, plus a
   scroll-to-center `useEffect` (a plain DOM `scrollLeft`/`scrollTop`
   mutation, not `setState`, so it doesn't hit the same lint restriction as
   above) so the one node the page is about is always in view on load. The
   old 16-node-per-ring display cap and "N more (too many to fit)" overflow
   list are gone entirely — the backend's `_MAX_GRAPH_NODES` cap plus
   `truncated` banner replaced them, since "list the rest below" doesn't
   make sense once some of those nodes are two or three hops away rather
   than direct neighbors.

**Two more real-usage findings on the modules list, plus a broad UI/UX
audit (recorded 2026-11-10):**

- **Native `<select>` dropdown arrow asymmetric, no gap before the border**
  (`frontend/app/modules/page.tsx`): the user flagged this directly off a
  screenshot (the real complaint was specifically "no gap between the arrow
  and the button's edge," not a general aesthetic opinion). `padding-right`
  doesn't reliably control a native select's own browser/OS-drawn arrow —
  confirmed broken even after bumping padding (Chrome on macOS still
  rendered it flush against the border). Fixed properly instead of
  re-tuning padding again: `appearance-none` hides the native arrow
  entirely, replaced by a real `lucide-react` `ChevronDown`, absolutely
  positioned and vertically centered (`top-1/2 -translate-y-1/2`), wrapped
  in a small local `FilterSelect` component reused by all four selects on
  the page (3 filters + the pagination page-size picker).
- **Module-list `Name` column crushed unreadable on a narrower window**
  (same file): every real module in this project's own scanned fleet
  shares a long `Vendor_` prefix (mostly `Magento_`) — `table-fixed`
  splitting the leftover width four ways (Name, Composer name, Quality,
  Tags) meant a narrower window crushed every row's name down to the same
  truncated prefix, telling a user nothing about which module they were
  looking at (reported directly: "skad user ma wiedziec jaki modul oglada
  jak na malym monitorze wszystkie wygladaja tak samo"). `Name` now gets
  its own fixed floor (`w-52`) instead of sharing that split; Composer
  name/Quality/Tags got `min-w-*` floors of their own. Getting this to
  actually work needed one more change, not just adding the floors: the
  `<Table>` itself had to switch from an exact `w-full` to `w-auto
  min-w-full` (confirmed via inspecting the rendered `class` list that
  `cn`'s tailwind-merge dedup genuinely drops the conflicting `w-full`
  rather than leaving both) — with a hard `width:100%`, `table-fixed`
  still forced every column down toward 0 regardless of any column's own
  `min-width`, which is what caused the first attempt (floors with no
  table-width change) to visibly fail: header text overlapping into the
  neighboring column instead of the table overflowing into the
  container's already-present `overflow-x-auto` scroll.

Both of the above were found live, by a real user looking at the deployed
app, not by review — which prompted explicitly asking a subagent to go
hunt for more of the same class of problem (`AskUserQuestion`-free,
direct instruction: "puść subagenta niech poszuka problemów z ui/ux").
The agent screenshotted every page via Playwright at three widths (~900px
"small monitor" — exactly where both bugs above were found — ~1500px
desktop, ~380px phone) and reported, prioritized:

- **Mobile `ModuleCard`/repo-card badge clipped off-screen** (`/modules`
  and `/repos`, ~380px): a `flex justify-between` row (long name/path on
  the left, a fixed-size badge/count on the right) with no `min-w-0` on
  the text side — the flex item's default min-width is its own content
  width, so instead of truncating, the long text just pushed the badge
  past the right edge of the phone screen entirely. Same fix both places:
  `min-w-0 truncate` (plus a `title` tooltip) on the text span, `shrink-0`
  on the sibling that must never give up space.
- **Stats "Top modules by quality findings" bar chart unreadable on
  mobile** (`frontend/app/stats/page.tsx`): Recharts' `YAxis` needs a real
  pixel `width`, not a responsive unit — a `width={210}` label column left
  almost nothing for the actual bars on a 380px screen (reported as bars
  squeezed to a ~2px sliver, defeating the whole point of a magnitude
  comparison). Added `frontend/lib/use-media-query.ts` (a small
  `useSyncExternalStore` hook, same style as the existing
  `use-query-param.ts`) to detect `(max-width: 480px)` and switch to a
  narrower axis width (88px) with a `tickFormatter` that truncates labels
  to 11 characters. Truncating from the *end* would recreate the exact
  "every name becomes the same prefix" bug fixed above — these labels are
  real module names sharing the same `Magento_` prefix — so the formatter
  keeps the *tail* instead (`…` + last N chars).
- **Dependency graph: depth 2 and depth 3 can render identically with no
  explanation** (`frontend/app/modules/[id]/graph/GraphClient.tsx`): once
  the backend's node cap is hit at or before the shallower depth, a deeper
  depth looks pixel-identical with no indication why. Now always shows a
  live `"{n} nodes shown"` count next to the graph (not just when
  truncated), so the same count appearing at both depths is self-evident
  instead of silently mysterious, plus a clearer truncation message.
- **Dependency graph: no affordance that it's pannable** (same file): the
  force layout routinely produces a canvas wider than its bordered box
  (depth > 1, or any well-connected hub module) with nothing — no visible
  scrollbar cue, no hint text — signaling there's more to see. The
  existing scroll-to-center `useEffect` now also measures
  `scrollWidth`/`scrollHeight` against the container's own
  `clientWidth`/`clientHeight` right after centering and sets a
  `canScroll` flag; true, a "scroll/drag inside the graph to see the
  rest" hint appears next to the node count.
- **Flagged but not changed:** a dense depth-2/3 graph on a
  well-connected hub module becomes a hard-to-trace tangle of crossing
  edges even with no overlapping labels — likely inherent to force-directed
  layout at that edge density rather than a clear bug, left as-is.

Everything else the audit checked (module detail page at all three
widths, chat, settings, search/row-expand on the modules list, the
dependency graph on mobile) came back clean.

**Phase 13, for real: Fly.io + Neon instead of GCP/Azure/Terraform
(recorded 2026-11-10):** CLAUDE.md's Phase 13 always named GCP/Azure via
Terraform, deferred for lack of cloud budget. The actual trigger this
session was wanting something to link from a LinkedIn post, and "a GIF
instead" was the explicitly considered, cheaper alternative — Fly.io
(scale-to-zero free allowance) + an external managed Postgres was decided
as the still-cheap, still-real middle ground over either extreme.

- **Neon over Fly's own Postgres**: researched live rather than assumed —
  pgvector support on Fly's *managed* Postgres (MPG) is unconfirmed/
  inconsistent as of this writing (community threads asking for it with no
  official "yes" found), and legacy Fly Postgres needs a custom image
  built with pgvector baked in, unsupported/fragile territory. Neon
  supports `CREATE EXTENSION vector` natively on its free tier with zero
  extra setup — confirmed directly (`vector 0.8.6` installed in under a
  minute).
- **Two separate Fly apps** (`magewiki-api`, `magewiki-web`), not a
  monorepo-wide single deploy — Fly's own GitHub-import "launch" flow
  can't one-click a multi-service docker-compose project with no root
  Dockerfile (confirmed by letting the user's own first attempt fail with
  "Could not find a Dockerfile, nor detect a runtime or framework from
  source code" before building anything). `backend/fly.toml` points
  straight at the existing (already-production-appropriate, no `--reload`)
  `backend/Dockerfile`. `frontend/Dockerfile.fly` is a **new**, separate
  multi-stage Dockerfile specifically for Fly — the existing
  `frontend/Dockerfile` runs `npm run dev` (fine for the bind-mounted,
  hot-reloading local docker-compose workflow, wrong for a public
  deployment), so reusing it would have shipped an unoptimized dev server
  publicly. Added `output: "standalone"` to `next.config.ts` (`next build`
  output shape only, `next dev` unaffected) so the production image copies
  just that self-contained server directory instead of the whole
  `node_modules` tree.
- **No worker/php-analyzer/Redis on Fly**: nothing in the public demo
  enqueues an ARQ job (no live scanning — no persistent Magento checkout
  exists on an ephemeral Fly Machine to scan anyway; no AI analysis — no
  LLM key is configured there either, a deliberate choice, see below).
  `get_arq_pool()`'s connection is lazy (confirmed in
  `app/tasks/queue.py`), so the API never touches Redis at boot; only an
  actual `POST /scan`/analysis call would, and those paths are simply left
  unconfigured (`MAGEWIKI_SCAN_ROOT_*` unset) rather than specially
  disabled.
- **No LLM key set as a Fly secret, deliberately**: a public, unauthenticated
  demo with a real paid API key behind its chat endpoint is a cost-abuse
  surface no amount of `LLM_MONTHLY_BUDGET_USD` capping fully closes (it
  bounds the damage, not the annoyance of hitting it). Chat is left
  genuinely non-functional on the public deployment rather than faked or
  rate-limited — the demo's value is the already-collected real data
  (modules, quality findings, AI docs, dependency graph), not a live LLM
  surface.
- **Seeded the demo DB from this project's own real local dev data**, not
  a fresh scan: `pg_dump --data-only` of the already-scanned local
  Postgres (a real ~225-module fleet: Magento core + the author's own
  `Ordo_Automation` third-party module), excluding `analysis_cache` (423MB,
  a pure internal cost-optimization cache, never read by the UI) and
  `chunks` (395MB, RAG embeddings — moot anyway with no LLM key configured
  for chat). `file_analyses`/`module_docs` both FK-reference
  `analysis_cache.id`, so the excluded cache's *referenced* subset (2,562
  of 58,874 rows — the other ~56k are stale/unused) had to be restored
  too, found only by hitting the FK violation on the first restore attempt
  and re-deriving it from `file_analyses`/`module_docs`'s own distinct
  `cache_id`s rather than guessing a size cutoff. One stray row,
  `Vendor_Module` (the committed `backend/tests/fixtures/demo-store`
  fixture, with placeholder/no-op content), had leaked into the local dev
  DB from earlier e2e runs and rode along in the first dump — caught
  immediately by the user clicking into it on the live demo and seeing
  obviously-fake content, deleted by id once identified.
- **Default sort changed, not just the demo's data**: with only 19 of 225
  modules having a real AI doc (budget-capped incremental analysis — true
  of *any* fleet at this project's current scale, not a demo-only
  artifact), plain alphabetical-by-name sorting showed "not analyzed yet"
  for whichever module's name happened to come first alphabetically — a
  real, reproduced complaint on the live demo ("mialy byc tylko te z
  opisem AI na gorze," after a `?has_doc=true` URL filter was tried first
  and rejected as not good enough as the *default* experience).
  `frontend/app/modules/page.tsx` now sorts modules with a real AI doc
  first **by default**, with a `hasUserSorted` flag so an explicit click
  on any column header (including re-clicking "Name") still means literal,
  un-grouped sorting — the doc-first behavior only applies to the
  untouched initial view.
- **Cold start from scale-to-zero broke the first request after any idle
  period**: confirmed directly in `fly logs` — Fly's own proxy gave up
  ("failed to connect to machine: gave up after 15 attempts") a full
  second *before* the machine actually finished booting and started
  serving real 200s. Not an acceptable first impression for a link meant
  to be clicked cold off LinkedIn, so both `fly.toml`s switched to
  `min_machines_running = 1` / `auto_stop_machines = false` -- cheap
  enough (shared-cpu-1x, 512mb) to just stay warm instead of chasing a
  faster cold start.
- **OG image + `metadataBase`**: sharing the link anywhere (confirmed
  directly against a real WhatsApp share) showed a title/description with
  no preview image -- Next.js's og:image resolves against
  `metadataBase`, which defaults to `http://localhost:3000` if unset
  (unreachable from anywhere else). Added `app/opengraph-image.tsx`
  (a branded card via `next/og`'s `ImageResponse`, not a raw app
  screenshot -- cleaner at thumbnail size) and a `NEXT_PUBLIC_SITE_URL`
  build arg (same inlined-at-build-time mechanism as the existing
  `NEXT_PUBLIC_API_URL`) feeding `metadataBase`.
- **CI auto-deploy**: a new `deploy` job in `.github/workflows/ci.yml`,
  gated on `push` to `main` only and on the jobs that actually prove the
  app builds/works (`backend`, `frontend`, `docker-build`, `e2e-smoke`) --
  not on the already-non-blocking security-scan jobs. Installs flyctl via
  the official install script rather than pinning `superfly/flyctl-
  actions/setup-flyctl`, which ships no versioned release tags to pin to
  (only `@master`). `backend/fly.toml`'s own `release_command` (`alembic
  upgrade head`) runs the Neon migration as part of `flyctl deploy` --
  nothing extra needed in the workflow for that. The long-lived
  `FLY_API_TOKEN` (an org-wide deploy token, `fly tokens create org`) was
  minted and added as a GitHub repo secret by the user directly -- both
  actions are correctly gated by this environment's own auto-mode
  classifier as sensitive/standing-access changes, not something to work
  around.

Local/router-side DNS caching produced a long, confusing side-quest mid-session
(a home router had cached a negative/NODATA answer for `magewiki-api.fly.dev`
from the few seconds between the app being created and its DNS actually
propagating, and kept serving that stale answer well after the record was
live) -- resolved only by pointing the Mac's own DNS at 1.1.1.1/8.8.8.8 to
bypass the router's resolver entirely. Not a MageWiki-AI bug; recorded here
only so a future session facing "the API is unreachable but curl with a
forced IP works fine" recognizes the shape immediately instead of
re-diagnosing it from scratch.

**CI's first real Fly deploy failed: `frontend/public/` has no tracked
files (recorded 2026-11-10):** the production image build
(`frontend/Dockerfile.fly`) failed only in CI -- `COPY --from=builder
/app/public ./public`: `"/app/public": not found`. `public/` sat on disk
locally (leftover `create-next-app` scaffolding) but held zero tracked
files, and git never commits an empty directory -- a fresh checkout (CI's
own, and a local `git clone` reproducing the exact same failure, used to
verify the fix before pushing it) has no `public/` at all. Every earlier
manual `fly deploy` from this same session had silently worked only
because it ran against the author's own full working tree, which still
had the untracked directory on disk. Fixed with `RUN mkdir -p public` in
the builder stage, guaranteeing a source directory exists either way --
not by committing a placeholder file, which would've been an odd change
for an unrelated reason.

**Phase 18: quality-alert webhook (recorded 2026-11-10):** real feedback
relayed from a colleague (Mateusz Rynk) reviewing the demo -- their own
Jenkins pipeline already blocks on CVE scans, and the thing they'd most
want is continuous monitoring that notifies as soon as something
compromising appears, instead of requiring someone to check the UI.

- **Why `history.py`, not the per-module persist loop**: `_persist_module`
  in `orchestrator.py` deletes a module's existing `ModuleQualityFinding`
  rows *before* inserting the fresh ones, so the "previous" state is
  already gone from the DB by the time the new findings exist in memory --
  comparing there would need an extra query per module. Verified directly
  (not assumed) before building anything: `write_history_snapshots()`
  already holds both previous and current `finding_counts` side by side,
  once per module, at a single end-of-scan point, with zero extra query.
  `write_history_snapshots()` now returns the alert-worthy increases it
  finds along the way instead of nothing, and `orchestrator.py` fires
  `send_quality_alert()` right after its existing call -- a few lines, no
  second pass over the data.
- **One webhook call per scan, not per module**: a repo with several new
  issues at once reads as one summary notification, not a burst -- avoids
  spamming whatever `ALERT_WEBHOOK_URL` points at, and is the controlled
  signal the feedback actually asked for, not noise.
- **Plain webhook, not a Slack SDK or SMTP**: the user asked directly
  whether Slack or Google Chat integration was feasible -- both already
  work with zero adapter code, since the payload's top-level `text` field
  is exactly what a bare Slack Incoming Webhook URL or a Google Chat
  webhook both render directly. No new dependency, no provider-specific
  code; the operator points `ALERT_WEBHOOK_URL` at whatever they use.
- `ALERT_WEBHOOK_URL`/`ALERT_CHECK_TYPES` follow the exact "empty disables
  it" convention already established by `WEBHOOK_HMAC_SECRET` and
  `LICENSE_RISK_PREFIXES` in `app/config.py`. Default `ALERT_CHECK_TYPES`
  (`hardcoded_secret,security_advisory`) is deliberately narrow -- secrets
  and real CVEs, not routine PHPStan/PHPMD churn, which would make this
  noisy enough to ignore.
- Fails open on any webhook HTTP error (`httpx.HTTPError` caught and
  logged), the same convention as every other outgoing call in this
  codebase (`app/scanner/magento_github.py`'s release-fetching calls) -- a
  flaky notification endpoint must never fail the scan itself.
- Verified end-to-end through the real orchestrator path, not just the
  pure functions in isolation: a test drives a full `scan_repository_events`
  run against a fixture module containing a real AWS-key-shaped literal,
  with `send_quality_alert` monkeypatched to a spy, confirming it's
  actually invoked with the right module/check_type -- and a second test
  confirms a scan with nothing alertable invokes it with an empty list
  (always called, no-ops internally) rather than skipping the call
  entirely.

**Phase 19: cross-module conflict detection round 3 -- acl.xml, plus a new
unprotected-admin-controller check (recorded 2026-11-12):** another "po
kolei" roadmap round, this time started from a fresh research pass over the
actual codebase (grepped check_type/parser/embedding/chat-history/compare-UI
state) rather than re-mining `docs/v1-port-roadmap.md`, which was already
fully exhausted. Full scope requested explicitly after a scoping question --
the duplicate-ACL-resource-id conflict is the same `webapi_conflicts.py`-
style pattern already used four times; the unprotected-admin-controller
check is genuinely new ground, the first check in this codebase needing PHP
class *constant* extraction (`catalog_module_classes` previously only
captured class/interface/trait + methods + extends/implements, no consts).

- **`acl_resource_conflict`**: `app/scanner/acl_xml.py` parses `etc/acl.xml`
  (found via a `.//resources` descendant search, same defensiveness as
  `system_xml.py`'s `.//section`, rather than a fixed path assumption about
  the `<config><acl>` wrapper depth) into one `AclResource` row per
  `<resource>`, recursively flattened with `parent_id` kept for a future
  citation use even though the conflict check itself only needs
  `(resource_id, module_id)`. `acl_conflicts.py` groups by `resource_id`
  alone (no secondary attribute to compare, unlike `db_schema_conflicts.py`)
  -- same "flag a concrete, certain conflict" pragmatism as
  `webapi_conflicts.py`. New table `acl_resources` (migration 0036), new
  check_type `acl_resource_conflict` (migration 0037, combined with
  `missing_acl` below in one migration, mirroring how 0033 added three
  conflict check_types together).
- **`missing_acl`**: a `Controller/Adminhtml/*` class with no resolvable
  `ADMIN_RESOURCE` constant -- a real Magento security footgun (the admin
  action becomes reachable by any logged-in admin, not just one with a
  specific permission). The real design problem: `ADMIN_RESOURCE` is a PHP
  constant and PHP constants are inherited, but resolving a `use`-aliased
  parent class name to its real FQCN is infrastructure this project doesn't
  have anywhere, and building it was ruled out of scope for this phase
  during planning. `admin_acl.py`'s `find_missing_acl()` resolves
  `extends`/`implements` chains **only within the same module's own class
  catalog** (by unqualified name, the only resolution available without
  `use`-alias support): the chain reaching a class name the module doesn't
  define itself (e.g. the real `\Magento\Backend\App\Action`) stops
  resolution and does **not** flag -- ambiguous, can't be sure either way --
  while a chain that's fully resolvable in-module (including "no parent at
  all") and never finds `ADMIN_RESOURCE` is a certain, flaggable gap.
  Severity `warning`, not `blocking`, reflecting that real uncertainty.
  Abstract classes are excluded outright (not in the original plan -- added
  during implementation once `abstract_modifier` turned out to be trivially
  readable from tree-sitter-php's own grammar): Magento's own base
  admin-controller classes are routinely abstract with no `ADMIN_RESOURCE`
  of their own by design, since only a concrete subclass is ever dispatched.
- **New tree-sitter-php capability**: `PhpClassEntry` gained `consts: dict[str,
  str]` and `is_abstract: bool`. Constant *values* are captured only for a
  simple, non-interpolated string literal (`node.type in ("string",
  "encapsed_string")` with exactly zero or one `string_content` child,
  verified empirically against the real grammar shape before writing the
  extraction code, same discipline this project already applies elsewhere)
  -- a concatenation, a `self::OTHER`-style constant reference, or any
  non-string literal is left out rather than guessed, since those are
  unresolvable without evaluating an expression. Neither field is persisted
  to the `php_classes` table -- `find_missing_acl` consumes the in-memory
  `catalog_module_classes()` result already computed once per module in
  `_persist_module`, not a second parse pass or a DB round-trip.
- Both new check_types are correctly categorized in
  `_FILE_HASH_DEPENDENT_CHECK_TYPES`: `missing_acl` belongs there (purely a
  function of this module's own PHP files, same as `deprecated_annotation`),
  `acl_resource_conflict` does not (fleet-wide, like every other `_conflict`
  type already in the family) -- confirmed by checking that no existing
  `_conflict` check_type is in that tuple before adding the new one.
- Drive-by fix, flagged during research and folded into the same edit:
  `agent/tools.py`'s `list_modules` tool description had drifted out of sync
  with the real check_type list since migration 0033 (missing
  `preference_conflict`/`cron_job_conflict`/`graphql_field_conflict`) --
  resynced in full while adding the two Phase 19 types to the same string,
  rather than compounding the drift with a fourth untracked gap.
- Verified end-to-end: full backend suite (701 passed, 2 skipped -- the
  Ordo-fixture-gated tests, unrelated), full frontend suite (229 passed,
  one pre-existing stats-page test updated for the new tile member), a real
  `alembic downgrade`/`upgrade head` round-trip against a live Postgres
  (not assumed from the migration file alone), and `ruff check`/`tsc
  --noEmit`/`eslint` all clean. `ruff format --check` was deliberately not
  used as a gate -- it would reformat most of this project's own pre-existing,
  intentionally-long-line code too, confirming it isn't part of this
  project's actual enforced style despite `pyproject.toml`'s `line-length =
  100`.
- **Not done this round**: the README's existing "Cross-module conflict
  detection" section only ever documented the original five checks (plugin/
  composer/webapi/db_schema/circular) and was already stale before this
  phase -- it never got the three Phase 15 additions
  (preference/cron/graphql) either. Left alone deliberately rather than
  folding an unrelated pre-existing docs gap into this phase's diff; flagged
  to the user as a separate docs-sync candidate.

**e2e coverage for every fleet-wide conflict check + security_advisory/
abandoned_dependency (recorded 2026-11-12):** asked directly after Phase 19
("czy mamy wszystkie niezbedne testy... e2e playwright?"). Audit: of 24
check_types, only 2 (`composer_completeness`, `magento_version_blocker`) had
any Playwright assertion at all, and even those were generic "tile is
nonzero" checks -- every cross-module conflict check and both externally-
backed checks had zero e2e representation. Asked how far to close this; the
user chose the broadest option (every fleet-wide conflict + the new acl
checks + security_advisory/abandoned_dependency, explicitly not
license_risk/phpunit_failure/the PHP-toolchain findings).

- **Why a brand-new fixture, not a sibling added to `demo-store`**: confirmed
  by reading `orchestrator.py` that all 10 cross-module conflict queries
  filter `Module.repo_root == str(root)` -- a module only ever gets compared
  against siblings under its *own* scan root, never against a different
  repo. A colliding sibling would therefore need to live in `demo-store`
  itself, which would break ~8 existing exact-count assertions
  (`repos.spec.ts`'s "1 module"/"1/1 enabled", `test_scanner_integration.py`'s
  `tasks_enqueued == 7`, `test_scan_api.py`, `test_cli_internals.py`).
  Instead: `backend/tests/fixtures/conflict-store/`, two synthetic modules
  (`Vendor_ConflictA`/`Vendor_ConflictB`) that conflict with *each other*
  under their own new scan root (`MAGEWIKI_SCAN_ROOT_2`) -- zero risk to any
  existing fixture-dependent assertion. Each minimal shape (plugin/
  composer/webapi/db_schema/circular/preference/cron/graphql/acl conflict,
  plus a `Controller/Adminhtml` class with no `ADMIN_RESOURCE` on ConflictA
  only) copied from this project's own `test_orchestrator_*_conflicts.py`
  fixtures, not invented from scratch -- verified first at the much faster
  pytest layer (`test_conflict_store_fixture.py`, asserting every expected
  check_type lands on the right module) before ever touching Playwright.
- **A real bug this surfaced, not a flaky test**: the first version of the
  fixture used `guzzlehttp/guzzle` (`^6.0` on ConflictA, `^7.0` on B) for
  `composer_conflict`, seeded nothing for it, and assumed no network call
  would matter. The real docker-compose `api` container *does* have outbound
  internet, and guzzlehttp/guzzle has real historical Packagist security
  advisories overlapping one of those ranges -- `security_advisory`'s count
  came back non-deterministic (passed locally with no internet, failed in
  the real stack with internet), exactly the live-dependency flakiness this
  project's own `packagist_cache` design exists to avoid everywhere else.
  Fixed by renaming the `composer_conflict` package to a fully fake
  `vendor/conflict-version-probe` and seeding its cache "clean" (empty
  advisories, a version satisfying ConflictA's `^6.0` so it doesn't also
  read as outdated there) -- now provably network-independent regardless of
  what real-world Packagist data does in the future.
- **Seeding `security_advisory`/`abandoned_dependency` deterministically**:
  confirmed directly (`app/scanner/packagist_cache.py`) that both checks read
  the cache *before* ever reaching `httpx` -- pre-seeding a `packagist_cache`
  row makes the real scan use it with zero network traffic, the same
  mechanism this project's own `test_abandoned_dependencies.py` cache-hit
  test already proves. New `app/cli.py` subcommand,
  `seed-packagist-cache <cache_key> <json>` (plain `argparse`, same shape as
  `scan`/`resume-*`), calls `set_cached()` directly -- not a new HTTP route,
  since `docker compose exec api python -m app.<module>` is already this
  project's own documented pattern (README.md) for one-off operational
  commands, and a CLI command reachable only via `docker compose exec`
  carries zero new attack surface, unlike a web route would.
- **`frontend/tests/e2e/global-setup.ts`** now loops to a second scan root
  when configured: seeds three `packagist_cache` rows via
  `execFileSync("docker", ["compose", "exec", "-T", "api", ...])` (array
  args, not a shell string, so the JSON payload's own quotes never need
  escaping), then `POST /scan`s `conflict-store` the same way `demo-store`
  already was. `docker-compose.yml` needed zero changes (`MAGEWIKI_SCAN_ROOT_
  1/2/3` were already generically bind-mounted into api/worker/php-analyzer);
  `.github/workflows/ci.yml`'s `e2e-smoke` job needed exactly one new line
  setting `MAGEWIKI_SCAN_ROOT_2`.
- **Two pre-existing `repos.spec.ts` tests broke, for real reasons, once a
  second repo actually existed**: "Download SBOM" became a strict-mode
  ambiguous match (one button per repo card, now two cards), and
  `"1 of 1 modules"` stopped being true (the denominator is the *unfiltered*
  total across every repo, confirmed by reading `app/modules/page.tsx`, not
  per-repo) once conflict-store's two modules joined demo-store's one. Fixed
  by scoping the first test to the demo-store repo card specifically (same
  `a[href="/modules?repo=..."]` locator the second test already used) and
  loosening the second to `/^1 of \d+ modules$/` -- the same fix this
  session's own `conflicts.spec.ts` already needed for the identical reason.
- **Local verification required a real safety detour**: this machine's own
  root `.env` has `DATABASE_URL` pointed at the real production Neon
  instance (the public demo's database) -- `docker-compose.yml`'s
  `env_file: .env` directive reads that literal file regardless of `docker
  compose --env-file`, which only affects `${VAR}` substitution inside the
  compose YAML, not `env_file:`-loaded variables. Asked the user before
  touching it; backed up the real `.env` to the scratchpad directory first,
  overwrote it with a safe all-local-docker version (local `db`/`redis`,
  no LLM/embedding keys, both scan roots), ran the full real
  `docker compose up -d --build` + `npx playwright test` (27/27 passed) +
  full backend pytest (704 passed) against that, then restored the original
  `.env` from the backup and diffed it byte-for-byte to confirm an exact
  restore before doing anything else.

**e2e coverage round 2: the last 10 check_types, two real bugs found along
the way (recorded 2026-11-12):** asked directly again, after round 1's
conflict-store work, what was still missing. Remaining: `hardcoded_secret`,
`deprecated_annotation`, `license_risk`, the five php-analyzer static-
analysis checks, `magento_php_incompatible`, `phpunit_failure`. User's
instruction: close every one. Added two more modules inside the same
`conflict-store` fixture: `Acme_QualityChecks` (every single-module
parser/cache-backed check plus the five static-analysis checks) and
`Vendor_PhpunitSample` (a real, deliberately failing PHPUnit run).

- **Bug 1 (real, significant, previously invisible): `MAGEWIKI_MAGENTO_
  FIXTURE_PATH`'s `docker-compose.yml` fallback was `/tmp`, not `/dev/null`
  like every other optional scan-root/fixture variable.** Left unset (its
  default, both locally and in `.github/workflows/ci.yml`'s `e2e-smoke` job
  — confirmed by reading the workflow directly, it's never set there), this
  bind-mounts the *host's* `/tmp` read-only onto the *container's* `/tmp`
  for `api`/`worker`/`php-analyzer` alike. Found because `phpstan`/`phpmd`/
  `phpcs`/`rector`/`phpmetrics` all silently returned zero findings against
  a fixture deliberately written to trigger each one — traced to a real
  `mkdir(): Read-only file system` (phpstan's own cache dir) and a `PHP
  Fatal error: Uncaught ValueError: Path must not be empty` inside PDepend's
  Symfony-DI container compilation (phpmd/phpmetrics), both from having
  nowhere to write a temp file. **This means every one of these five
  check_types has effectively never produced a real finding in CI**,
  against any fixture, for as long as this variable has existed unset there
  — not because the scanned code was clean, but because the tools couldn't
  write anywhere. Fixed with a one-line `docker-compose.yml` change (the
  fallback for all three services, matching the `/dev/null` convention
  every other optional path variable already uses) — this is an app/infra
  fix, not test-only, so it benefits every real user's own local
  `docker compose up` too, not just this fixture.
- **Bug 2 (real, narrower, also previously invisible): `php-analyzer`'s
  `run_phpmd()`/`run_phpcs()` exclude/ignore flags (`--exclude vendor/*`,
  `--ignore=*/vendor/*,*/Test/*`) match case-insensitively against a literal
  "Vendor" path *segment*, not just an actual nested `vendor/` directory.**
  Found after fixing Bug 1 still left phpmd/phpcs at zero findings while
  phpstan/rector/phpmetrics (which configure their excludes via a neon/php
  config file, not a CLI flag) worked correctly on the exact same fixture.
  Isolated with a clean-room reproduction via `proc_open()` directly inside
  the real `php-analyzer` container (bypassing any shell-quoting doubt):
  copying the identical fixture content to `/tmp/probe/Acme/Test1` (no
  "Vendor" anywhere in the path) made both tools work immediately with the
  *exact same* exclude/ignore flags unchanged. **Every module this project
  has ever scanned under `app/code/Vendor/...` — meaning literally every
  committed test/demo fixture (`demo-store`, `conflict-store`'s own
  `ConflictA`/`ConflictB`) — has had `phpmd_issue`/`phpcs_violation`
  silently return zero findings this whole time**, regardless of what the
  code actually contains. Real customer stores are unaffected in practice
  (a real company's Composer vendor namespace is essentially never
  literally the word "Vendor"), which is exactly why this stayed invisible
  through real-world use against Ordo_Automation (vendor namespace `Ordo`)
  while still being latently broken for this project's own fixtures.
  **Deliberately not fixed in `php-analyzer` this session** — the right fix
  needs to decide how to make the exclude pattern not collide with a
  legitimate company-namespace segment in general (not just rename this
  one fixture), which is a real behavior change to production scanning
  logic deserving its own dedicated look, not a same-session patch bundled
  into test-fixture work. Worked around for *this* fixture by giving the
  one new module that needs `phpmd_issue`/`phpcs_violation` coverage an
  `Acme_` namespace instead of `Vendor_` — zero risk (a brand-new,
  never-committed module), and it's the only one of the four `conflict-
  store` modules that needs those two checks to fire at all.
- **`phpunit_failure` needed its own, fourth module, split out from
  `Acme_QualityChecks`**: a committed `vendor/bin/phpunit` (the official
  PHPUnit 11.5.47 `.phar`, ~5.7MB, downloaded from `phar.phpunit.de` and
  committed as-is — approved explicitly after flagging the binary-blob
  tradeoff and that it reverses this project's earlier choice to only ever
  verify this check against an uncommitted real-world fixture) at a
  module's root was *also* initially suspected to be part of Bug 2, since
  removing it was the first thing tried — turned out unrelated (Bug 2 fired
  regardless, confirmed by testing with the phar already removed), but
  splitting it out stood anyway: a `vendor/` directory containing a ~5.7MB
  binary at a module's root is a plausible separate risk for any directory-
  walking tool's performance/behavior, and `phpunit_failure` doesn't need
  to coexist with the static-analysis triggers in the same module at all.
  `php-analyzer` has no internet route at all (`docker-compose.yml`'s
  `php_analyzer_net` is `internal: true`) and mounts are read-only, so a
  real `composer install` is categorically impossible there — the `.phar`
  bundles every PHPUnit dependency itself, and the one test extends
  `PHPUnit\Framework\TestCase` directly with no need for the module's own
  autoloading, so no `vendor/autoload.php`/bootstrap was needed either.
- **`magento_php_incompatible` reuses the exact same seeding mechanism as
  round 1's Packagist checks, no new code**: `app/scanner/magento_github.py`
  turned out to already share the one `packagist_cache` table/API with
  `security_advisory`/`abandoned_dependency` (cache keys `"magento-github:
  latest-release"` and `"magento-github:<tag>:composer.json"`) — the
  existing `app.cli seed-packagist-cache` subcommand needed zero changes to
  seed these too.
- A real, pre-existing `stats.spec.ts` assertion broke for a genuine reason
  once `Vendor_PhpunitSample`'s real `Test/Unit/` directory joined the
  fleet: "Have tests" stopped being a guaranteed 0% across every scanned
  module. Loosened to assert a real percentage renders (matching how the
  rest of that test already treats non-deterministic-count fields) rather
  than hardcoding the now-false "still always zero" assumption.
- Verified exactly like round 1: a quick pytest check of the parser/cache-
  backed checks first, then the full real stack (`.env` swap/restore
  protocol, approved again for this round) — full Playwright suite (29/29
  passed, up from 27) and full backend pytest (704 passed) green before
  committing.

**php-analyzer's phpcs ancestor-"Vendor" exclusion bug: the real fix
(recorded 2026-11-12):** the round above worked around this by naming one
module `Acme_QualityChecks` instead of `Vendor_QualityChecks`. User asked
for the real fix in a follow-up round. A focused Explore pass read the
actual *installed* tool source (not docs or assumption) to settle the exact
mechanism before touching anything, since the previous round's own
empirical tests left it ambiguous whether phpmd was also affected:

- **`squizlabs/php_codesniffer` 3.13.6 is the entire, confirmed root
  cause.** `Config.php:1207-1230`: every CLI `--ignore=` pattern is
  hard-coded to `type='absolute'` — there's no CLI way to request
  `'relative'` matching at all (only a ruleset XML `<exclude-pattern
  type="relative">` element can, and `--basepath=` only changes how paths
  are *displayed in reports*, confirmed by its own doc-comment, never
  ignore-matching). `Filters/Filter.php`'s `shouldIgnorePath()`: for an
  `'absolute'` pattern, the string tested is the file's *raw, full
  absolute path* — `$this->basedir` (set to the real scan argument) is
  computed but never consulted for this type. A bare `*/vendor/*` becomes
  the regex (case-insensitive, zero anchors) via a plain `strtr(['*' =>
  '.*'])` — a pure, unconstrained substring search over the entire path.
  Any ancestor directory merely *named* "Vendor" (case-folded) anywhere
  above the scan root matches it, excluding every file.
- **`phpmd/phpmd` 2.15.0 + `pdepend/pdepend` 2.16.2 turned out NOT actually
  vulnerable, as `index.php` invokes it today** — contradicting what the
  previous round's own empirical tests seemed to show. `Engine::
  addDirectory()` realpath()s the given directory and that becomes
  `$rootPath`; `Input/Iterator::getLocalPath()` strips that exact root
  prefix from each file's path *before* `ExcludePathFilter` ever sees the
  string, so a `Vendor` ancestor segment sits outside the stripped string
  entirely and can never match. (The previous round's phpmd failures were
  most likely cross-attributed from phpcs's output in the same combined
  test pass, or a transient side effect of chasing the `/tmp` bug fixed in
  the same session — not re-litigated further since the fix below is
  applied to both tools anyway, for defense-in-depth and to keep their
  exclude logic parallel/auditable.)
- **Fix** (`php-analyzer/public/index.php`, both `run_phpmd()` and
  `run_phpcs()`): anchor the exclude pattern to the real, already-
  `realpath()`'d `$modulePath` the function already has, instead of a bare
  wildcard -- `'vendor/*'` → `$modulePath . '/vendor/*'` for phpmd;
  `'--ignore=*/vendor/*,*/Test/*'` → `'--ignore=' . $modulePath .
  '/vendor/*,' . $modulePath . '/Test/*'` for phpcs (dropped the extra
  leading wildcard for `Test/` too — Magento's own convention always puts
  a module's `Test/` directory directly at its root, the same assumption
  `php_analyzer_client.py`'s own phpstan `excludePaths` already makes).
  A match can now only ever occur for a genuine `vendor/`/`Test/`
  directory physically inside the scanned module, never an ancestor
  segment above it -- zero behavior change for any real, legitimate
  exclusion case.
- **`Vendor_QualityChecks` renamed back from `Acme_QualityChecks`** now
  that the real bug is fixed -- restores naming consistency with its
  siblings and turns into a better regression test than the `Acme_`
  version ever was (a future regression in this exact anchoring would make
  it go quiet again, which is exactly the scenario being guarded against).
- **Verified against the real container, not assumed**: deleted the
  fixture's module rows from a stale local DB first (left over from this
  same session's earlier `Acme_`/`Vendor_` rename, which was silently
  masking the real fix behind the orchestrator's own "unchanged file hash,
  skip recompute" logic -- a real, if self-inflicted, local-verification
  trap, not a production concern since a real CI run always starts from a
  fresh database), then a clean rescan: `Vendor_QualityChecks` now shows
  all 10 of its designed check_types with exact counts matching
  `quality-checks.spec.ts`'s own assertions (`phpcs_violation` 7,
  `phpmd_issue` 4, etc.), `demo-store`'s `Vendor_Module` still shows zero
  phpmd/phpcs findings (genuinely clean code, not a new false positive),
  and `conflict-store`'s `ConflictA`/`ConflictB` picked up real,
  previously-invisible `phpmd_issue`/`phpcs_violation` findings of their
  own now that the tools actually run on them too. Full Playwright (29/29)
  and full backend pytest (704) green afterward; `.env` restored and
  diffed byte-for-byte again before anything else.

**Phase 20: cross-module conflict detection round 4 -- indexer.xml/mview.xml
(recorded 2026-11-12):** next item in the CLAUDE.md roadmap after Phase 19,
done "po kolei" the same session. Same exact pattern as every prior round
in this family (`webapi_conflicts.py`'s exact-duplicate-key shape): two
modules declaring the same `indexer.xml` `<indexer id="...">` or the same
`mview.xml` `<view id="...">` hit the identical declarative-merge silent-
override risk already covered for `di.xml` preferences/`db_schema.xml`
columns/`acl.xml` resources.

- Neither `indexer.xml` nor `mview.xml` has a real example anywhere in this
  repo to verify against (unlike acl.xml/webapi.xml, which this project's
  own fixtures already exercised) -- schema confirmed via web search
  against real Magento core documentation/examples instead, then verified
  working end-to-end against synthetic fixture XML in the orchestrator
  integration tests (the same "verify directly" discipline this project
  applies everywhere, just via a different source since no local Magento
  checkout exists here).
- **Two separate tables (`module_indexers`, `module_mviews`), not CLAUDE.md's
  own roadmap-note shorthand of a single "module_indexers" table for
  both** -- `indexer.xml` and `mview.xml` facts have different attribute
  shapes (`indexer_id`/`view_id`/`class` vs `view_id`/`class`/`group`), and
  this codebase's own convention is one table per distinct fact shape
  (`DbTable`/`DbColumn`, `CronJob`, `GraphQlField`, `AclResource` are all
  separate too) -- the roadmap note was shorthand written before scoping
  this phase properly, not a binding design decision.
- `mview.xml`'s `group` attribute is stored as `group_name` on
  `ModuleMview`, not `group` -- a reserved SQL word, same reason other
  columns in this schema avoid bare reserved words.
- Extended the existing `conflict-store` fixture (`Vendor_ConflictA`/
  `Vendor_ConflictB`) with colliding `indexer.xml`/`mview.xml` declarations
  rather than building a new fixture -- purely additive new files on
  already-proven, already-committed modules, zero risk to anything
  already passing. The `mview.xml` subscribes to `conflict_sample_table`,
  the same table each module already declares in its own `db_schema.xml`
  from Phase 19's round, for a touch of realism.
- Lighter verification than the last two rounds: this phase is pure
  lxml/SQL with no php-analyzer/static-analysis involvement, so the full
  `.env`-swap/real-docker-stack dance wasn't needed -- local `db`/`redis`
  plus the full backend pytest suite (724 passed, up from 704) and
  frontend vitest (229 passed) were sufficient, the same lighter path
  Phase 19 itself originally used before the two e2e-coverage rounds
  introduced the heavier real-stack discipline for php-analyzer-dependent
  checks specifically.

**Phase 21: semantic duplicate detection + a module comparison page
(recorded 2026-11-12):** last item in the roadmap, done "po kolei" the
same session as every phase before it. Two research passes (Explore
agents, one per side) before writing anything, since this touches both a
new backend query shape (pgvector cosine similarity over an *existing*
table, not a new scan) and new frontend pages — confirmed two real
simplifications this session's earlier assumption didn't anticipate:

- **No new "compare" backend endpoint at all.** `GET /modules/{id}`
  (`ModuleDetail`) already returns every field the compare page needs
  (tags, `finding_counts`, `dependencies`) — the compare page just fetches
  it twice (`useQuery(["module", a], ...)` / `useQuery(["module", b],
  ...)`), the *same* queryKey `ModuleDetailClient.tsx`'s own `moduleQuery`
  already uses, so arriving at compare from a module page (or from the new
  "Similar modules" card) that's already cached is an instant hit, no
  extra network round trip. Only one genuinely new endpoint was needed:
  `GET /modules/{id}/similar`.
- **The one new query** (`app/search/similar_modules.py`): a self-join CTE
  against `chunks` using the exact same `<=>` pgvector cosine-distance
  operator `hybrid.py`'s own semantic signal already uses (raw SQL via
  `text()`, not the SQLAlchemy `.cosine_distance()` comparator — this
  codebase doesn't use that API anywhere) — but simpler than
  `hybrid_search`, since both vectors being compared are *already stored*
  columns, so no query-embedding computation/string-formatting step is
  needed at all. `chunk_type = 'module'` (confirmed exactly one such row
  per module, written once per `embed_chunks` regeneration) is the stable
  "module embedding" to compare. Deliberately fleet-wide, not scoped to
  one `repo_root` -- unlike cross-module conflict detection, which must
  stay per-store to match Magento's own per-store declarative-merge
  semantics, "do we have two modules doing the same third-party
  integration" is a genuinely cross-repo question (Phase 11's own
  framing). `min_similarity=0.5` is an explicit, documented judgment-call
  default (same epistemic honesty as `LICENSE_RISK_PREFIXES`'s own "this
  project's own opinion" comment), not fetched from settings.
- **A real test-isolation trap found and fixed while writing
  `test_similar_modules.py`**: this project's own `db_session` fixture
  (`tests/conftest.py`) never rolls back between tests -- every committed
  row from every earlier test in the same pytest run is still real,
  queryable data. Existing tests get away with this via unique
  names/repo_roots per test (`uuid.uuid4().hex[:8]` suffixes), but nothing
  before this needed per-test-*unique embedding vectors* too — a fleet-
  wide, non-repo-scoped query is exactly the first case where that matters:
  the first draft's tests all used the literal same one-hot vector
  (dimension 0) as "the identical/close vector," and once more than one
  test ran in the same session, each test's own "exact duplicate" started
  colliding with every other test's "exact duplicate" too, polluting
  results both ways (confirmed directly -- two tests failed with the
  *other* test's own leftover modules showing up as false matches). Fixed
  by deriving each test's own cluster of vectors from its own
  `uuid.uuid4()` suffix (`_base_dim()`), making different tests'
  vector clusters orthogonal to each other by construction.
- **No structured "integrations" field exists yet** (per the roadmap's own
  "tags, integrations, findings, dependencies" framing) — it's still only
  free text inside the AI-written README's own `## Integrations` section.
  Rather than scrape that out of markdown a second time just to populate
  one compare-page column, the compare page covers the three fields that
  *are* structured (tags/findings/dependencies) and links each column to
  its own full module page ("View full module →") for anything not shown
  side by side — an honest scope trim, not a silent gap.
- **"Similar modules" needed no embeddings in e2e, by design, and that's
  fine** — no e2e fixture has an LLM/embedding key configured (same
  constraint `module-detail.spec.ts` already documents for the AI-doc
  pending state), so nothing in the whole e2e fleet is ever embedded.
  Rather than invent a synthetic-vector seeding mechanism with no
  production equivalent (considered and rejected -- unlike
  `packagist_cache` seeding, which mirrors a real production code path, a
  hand-rolled pseudo-embedding generator would be pure test-infra
  invented from whole cloth), the empty state is asserted for real
  instead — the similarity *ranking logic itself* is already fully
  verified for real at the pytest layer (`test_similar_modules.py`,
  inserting real `Chunk` rows with controlled vectors, no AI call needed
  there, same as every other backend test). The **compare page**, by
  contrast, needs no embeddings at all and got full, real e2e coverage
  (`module-compare.spec.ts`) against `conflict-store`'s already-rich
  `Vendor_ConflictA`/`Vendor_ConflictB` fixtures.
- Verified like the php-analyzer rounds, not the lighter Phase 20 path —
  this one touches real frontend pages and a new route, so the full
  `.env`-swap/real-docker-stack dance ran again: full Playwright (31/31,
  up from 29) and full backend pytest (733 passed, up from 724) green
  before committing.

**Second feature-search round this session (recorded 2026-11-12):** with
the roadmap itself fully closed after Phase 21, this round found three
grounded gaps by auditing what the *last* round's own work hadn't fully
wired up, rather than inventing new scope — grepping for whether
`find_similar_modules` had ever reached the agent (it hadn't), checking
whether Phase 21's "Similar modules" had a fleet-wide equivalent to
`GET /modules/overlap` (it didn't), and re-reading this log's own
"known gap" notes for anything still genuinely open (the stale-types gap
above was still open). Three independent, small changes, three commits:

- **`find_similar_modules` agent tool** (`backend/app/agent/tools.py`):
  a thin dict-returning wrapper around the existing
  `app.search.similar_modules.find_similar_modules` — imported under a
  `_find_similar_modules` alias specifically to avoid shadowing the new
  tool function's own name, since every other tool function in this file
  already shares its exact name with its `TOOL_SCHEMAS` entry and this
  one needed to follow suit. No new query, no new scanning risk — purely
  wiring already-built logic into `TOOL_FUNCTIONS`/`TOOL_SCHEMAS`, plus a
  CLAUDE.md update to both the **Agent tools** list and the **Question
  routing** table (both "settled, always-relevant" per CLAUDE.md's own
  working-method rule, so they needed updating in the same commit, not
  left for the decision log alone).
- **Fleet-wide "possible duplicate modules" view**
  (`backend/app/search/similar_modules.py`'s new
  `find_duplicate_module_pairs`, `GET /modules/duplicate-pairs`,
  `frontend/app/repos/page.tsx`): the self-join query is almost identical
  to `find_similar_modules`'s own CTE, just without the `target` CTE
  anchoring it to one `module_id` — `c2.module_id > c1.module_id` in the
  join condition does the same job the original's `c.module_id !=
  target.module_id` did, while also ruling out mirrored (B,A) duplicates
  of the same pair a strict inequality alone wouldn't. Deliberately
  placed as a **third section on the Repos page**, not a Stats-page KPI
  tile — the Stats page's whole `KPI_TILES` structure
  (`frontend/app/stats/page.tsx`) is keyed by `ModuleQualityFinding.check_type`
  counts, and a cross-module pairwise relationship from embeddings simply
  isn't that shape. The Repos page already had the right sibling slot:
  `GET /modules/overlap`'s "Shared across stores" table solves a
  different-looking but conceptually adjacent problem (the exact same
  module name reused across `repo_root`s) in the exact same table-plus-
  empty-state layout this new section copies. Route had to be declared
  before `GET /modules/{module_id}` in `modules.py`, same ordering
  constraint `GET /modules/overlap` itself already required (FastAPI
  matches a static two-segment path against a dynamic one in declaration
  order). e2e coverage inherits the same honest split Phase 21 already
  established for "Similar modules": no e2e fixture ever gets a real
  LLM/embedding key, so `frontend/tests/e2e/repos.spec.ts` can only prove
  the graceful empty state for real; the actual threshold/exclusion logic
  is fully covered at the pytest layer (`test_similar_modules.py`,
  extended rather than given its own file, since both functions are
  pairwise-similarity queries over the same table).
- **CI check for stale `frontend/lib/api-types.ts`**: closes the "known
  gap" flagged in this same log on 2026-11-08 (see above). Placed inside
  the existing `e2e-smoke` job in `.github/workflows/ci.yml`, immediately
  after its "Wait for api and web to be ready" step — that job already
  brings up a live `api` container on `localhost:8000`, the exact
  host:port `npm run gen:types` (`frontend/package.json`) already
  targets, so the fix is two lines (`npm run gen:types` then `git diff
  --exit-code lib/api-types.ts`) with no new job, service, or secret.
  Verified for real, not just by reading the YAML: regenerated the types
  file against the actual locally-running stack, confirmed `git diff`
  came back clean once the regenerated file was committed, confirming
  the step as written would genuinely pass.
- Same `.env`-swap/real-docker-stack verification discipline as every
  round this session: full Playwright (32/32, up from 31) and full
  backend pytest (740 passed, up from 733) green, `.env` restored from
  backup and diffed byte-for-byte before finishing.

**Phase 22: cross-module conflict detection round 5 -- routes.xml
(recorded 2026-11-13):** a fresh, separate session's "po kolei" round,
started after the previous session's CI/coverage-cleanup PR (#22) was
reviewed and merged to main. Research grepped the actual codebase for
`routes.xml`/`frontName` (zero hits) rather than re-mining already-
exhausted sources, confirming it as the last common Magento declarative-
config file nothing here parsed yet.

- `parse_routes_xml(path, area)` takes `area` as an explicit parameter
  rather than guessing it from the path -- the file itself (`<config>
  <router id="standard"><route id="..." frontName="..."><module
  name="..." /></route></router></config>`) carries no area information;
  only the CALLER (which of the two fixed paths,
  `etc/frontend/routes.xml` or `etc/adminhtml/routes.xml`, it read) knows
  it. This also turned out to be required, not just a style choice:
  `_sync_module_children`'s generic `model_cls(module_id=module_id,
  **asdict(entry))` path (the same helper every other 1:N parsed-fact
  table already uses) needs the DTO's own fields to exactly match the
  model's columns, so `RouteEntry` needed an `area` field either way --
  simplest to have the parser set it directly from an argument rather
  than inventing a second wrapper dataclass just to attach `area` after
  the fact.
- Two check_types from one file (`route_id_conflict`/`frontname_conflict`),
  not one combined -- same acl_resource_conflict/missing_acl precedent:
  a duplicate route id (breaks `getUrl()` reverse-route resolution) and a
  duplicate frontName (breaks URL dispatch) are different real-world
  symptoms, and a module can collide on one without the other (covered by
  its own dedicated "only route ids collide, frontNames differ" test).
  Both group by `(area, key)`, not just `key` -- Magento's own uniqueness
  constraint for both route id and frontName is scoped per area, so the
  same value reused across frontend and adminhtml is not a conflict,
  verified both at the pure detect-function layer and end-to-end through
  a real `scan_repository_events()` run writing two real module
  directories to a tmp_path repo.
- `quality-badges.tsx` labels are `route-id-conflict`/`frontname-conflict`,
  not the more natural-sounding `route-conflict` -- `webapi_route_conflict`
  (a completely different file, REST API routes from webapi.xml) already
  owns that exact label; reusing it would make two different check_types
  render identical badge text.
- Conflict-store's fixture reused the existing `Vendor_ConflictA`/
  `Vendor_ConflictB` pair again (same `conflict_shared_*` naming
  convention already established for acl.xml/indexer.xml/mview.xml),
  adding one `etc/adminhtml/routes.xml` each with the same colliding
  route id AND frontName in one declaration -- deliberately triggers both
  new check_types from the same two files rather than needing four new
  fixture files to cover both independently.
- Verified like the php-analyzer/Phase-21 rounds, not the lighter Phase 20
  path -- this one touches real frontend badge text and a new area-scoped
  fixture, so the full `.env`-swap/real-docker-stack dance ran again: full
  Playwright (32/32) and full backend pytest (762 passed, up from 747)
  green, 100% backend line coverage maintained throughout, before
  committing.

**Phase 22b: fleet-wide total-findings trend chart (recorded 2026-11-13):**
part 2 of the same round, immediately after the `routes.xml` conflict
checks above. `GET /modules/{id}/history` (Phase 16) was confirmed the
only route reading `module_history_snapshots` -- the Stats page's KPI
tiles answer "what's true right now," the per-module history view answers
"what changed for one module," and nothing answered "is the whole fleet
getting better or worse."

- `get_fleet_trend()` reconstructs a fleet-wide timeline in Python, not a
  SQL lateral join: `module_history_snapshots` is deduplicated per module
  (one row per *change* -- see `app/scanner/history.py` -- not one row per
  scan), so there's no single "fleet state at date X" to read directly.
  Carrying each module's own last-known `finding_counts` forward in a
  plain `dict[module_id, int]` as the merged, chronologically-sorted
  timeline advances is simpler and safer than expressing "last known value
  per group as of each row" as a lateral join, and the whole fleet's
  history comfortably fits in memory at this project's scale (sparse
  change-events, not a dense time series).
- Route is `GET /modules/history/trend` -- three static path segments, so
  no ordering conflict with the existing `GET /modules/{module_id}/history`
  (FastAPI only matches routes with the same segment count, and no other
  3-segment route under `/modules/` shares a literal third segment of
  `trend`).
- The real test-isolation trap this one hit: `tests/search/test_fleet_trend.py`
  and `tests/api/test_fleet_trend_route.py` both insert real `Module` rows
  with `state="up_to_date"` to get real snapshots persisted, and `db_session`
  never rolls back between tests. The first full-suite run showed 4
  unrelated failures in `test_llm_settings_api.py` (its "how many
  already-embedded modules would be affected by an embedding-model change"
  check counts ALL `up_to_date` modules fleet-wide, with no scoping) --
  root-caused by running `test_llm_settings_api.py` alone (18/18 passed) vs.
  together with the new tests (4 failed), confirming leaked fixture rows,
  not a real bug in the embedding-model-change logic. Fixed by having both
  new test files delete their own `Module` rows (cascades to their
  snapshots via the existing FK `ondelete="CASCADE"`) before returning --
  same fixture-hygiene discipline Phase 21's own similarity tests needed
  for the same underlying reason (no rollback between tests + a fleet-wide
  query elsewhere).
- Frontend: `stats/page.test.tsx` used a single `fetchMock.mockResolvedValue(...)`
  for its one `/modules` call; adding a second endpoint on the same page
  meant every existing test's `/modules` fixture would have also silently
  answered the new `/modules/history/trend` query with mismatched data.
  Converted every call site to the `mockImplementation`-branch-by-path
  convention `repos/page.test.tsx` already established, via a small local
  `mockModules()` helper, rather than inventing a new pattern.
- Verified against the real stack again (full Playwright 33/33 -- including
  a new assertion that the chart renders real data from global-setup.ts's
  own first scan, not its empty state -- and full backend pytest 764/764,
  100% coverage) before committing.

**Phase 22c: `get_module_history` agent tool (recorded 2026-11-13):** part 3,
closing out the same round. `app/agent/tools.py` had zero mention of
history (confirmed via grep) even though `GET /modules/{id}/history`
(Phase 16) already exposed it over REST -- the same shape of gap
`find_similar_modules` closed earlier this session for Phase 21's
embeddings: real data sitting behind a REST endpoint the chat agent had
no way to reach, so a PM asking "what changed in this module recently?"
only ever got generic hybrid-search text with no real answer.

- Deliberately duplicates the REST route's own query (`ModuleHistorySnapshot`
  filtered by `module_id`, ordered `scanned_at` desc) rather than extracting
  a shared helper -- two short, simple call sites reading the same table is
  within this session's own established "three similar lines" tolerance,
  and `app/api/routes/modules.py` and `app/agent/tools.py` have no existing
  import relationship worth creating just for this.
- Same `found: False` / `found: True` dict shape every other tool in this
  file already returns (`get_dependencies`, `find_similar_modules`) --
  `module_name` plus a `history` list, `limit` defaulting to 10 (an agent
  asking "what changed recently" doesn't need the module's entire history,
  just the recent tail -- the REST page already covers "show me everything").
- Registered in both `TOOL_FUNCTIONS` and `TOOL_SCHEMAS`, and CLAUDE.md's
  own **Agent tools** list and **Question routing** table updated in the
  same commit -- both are "settled, always-relevant" reference material
  per CLAUDE.md's own working-method rule, not roadmap history, so they get
  edited directly rather than only recorded here.
- Tests mirror `find_similar_modules`'s own tool-test structure exactly
  (newest-first ordering, not-found, empty-history), reusing the file's
  existing `_make_bare_module` helper and the same explicit
  `delete(Module)`-after-test cleanup discipline Phase 22b's fleet-trend
  tests needed for the same db_session-never-rolls-back reason.
- Verified via the full backend pytest (767 passed, up from 764, 100%
  coverage maintained) -- no frontend or real-stack changes in this part,
  so no Playwright/`.env`-swap pass was needed.

**Feature-search round 4, part 1: di.xml virtualType conflict detection
(recorded 2026-11-13):** a fresh round, started from a research fork
grepping the actual codebase (check_type CHECK constraint, `app/agent/tools.py`,
`app/scanner/`) rather than re-mining `docs/v1-port-roadmap.md`. The user
approved all three of the fork's candidates via AskUserQuestion. This part:
`app/scanner/di_xml.py` already parsed `<virtualType name="X" type="Y">`
into `DiVirtualType` (wired through `_sync_module_children` since an
earlier round added the parser for completeness), but nothing detected a
conflict on it -- confirmed via grep of the `check_type` CHECK constraint.

- `detect_virtual_type_conflicts()` deliberately follows
  `preference_conflicts.py`'s "different value for the same key" shape, not
  `indexer_conflicts.py`'s "any duplicate key at all" shape: a virtualType
  `name` is routinely reused by its OWN author across several of its own
  di.xml declarations (composing a virtual class from multiple angles is a
  normal, intentional pattern), so only a genuine disagreement across ≥2
  modules -- a different backing `type` for the identical name -- is a real
  conflict, exactly the same reasoning `preference_conflict` already
  established for `<preference>`.
- Pure detection-only addition: no new parser, no new table, no new
  scanning risk -- `di_virtual_types` was already being populated every
  scan. Only a `check_type` CHECK-constraint migration was needed (no data
  migration).
- Extended the existing `conflict-store` fixture's `Vendor_ConflictA`/
  `Vendor_ConflictB` `etc/di.xml` files with one more colliding
  `<virtualType>` declaration each, same "extend, don't rebuild" pattern
  every prior conflict-detection round used.
- Verified via the full backend pytest (774 passed, up from 767, 100%
  coverage maintained) and frontend `tsc`/`eslint`/`vitest` (254 passed,
  `quality-badges.test.tsx`'s own generic "every declared check type gets a
  label" tests absorbed the new entry with no new test code needed, same
  as Phase 22's routes.xml badges). Real-stack/Playwright verification
  deferred to the end of this round (after part 3), per the approved plan.

**Feature-search round 4, part 2: `get_module_findings` agent tool
(recorded 2026-11-13):** part 2 of the same round. Confirmed via grep that
`ModuleQualityFinding` was referenced only inside `list_modules`'s
count-by-check_type query (a bare int), nowhere else in `app/agent/tools.py`
-- the chat agent had no way to answer "why does module X have a
hardcoded_secret finding?" with a real, citable file/line/message, directly
against CLAUDE.md's "every claim cited" rule. Same gap shape as
`find_similar_modules`/`get_module_history` earlier this session: real data
sitting behind a parser-only table with no agent-facing path to it.

- Same `found: False`/`found: True` dict shape every other tool in this
  file already returns, with an optional `check_type` filter (mirrors
  `list_modules`'s own optional filter) for a narrower "show me just the
  CVEs" ask without the agent having to filter a big list itself.
- Deliberately a new, separate tool rather than folding findings into
  `get_module`'s own response -- `get_module`'s response is already large
  (doc fields, dependencies, state) and a module can carry many findings;
  keeping it a separate, optionally-filtered call matches how
  `get_dependencies` is already split out from `get_module` for the same
  reason.
- Registered in `TOOL_FUNCTIONS`/`TOOL_SCHEMAS` and CLAUDE.md's own **Agent
  tools** list and **Question routing** table, same "settled reference,
  edited directly" treatment Phase 22c gave `get_module_history`.
- Tests mirror `get_module_history`'s own tool-test structure (real
  findings with exact field shape, check_type filter, not-found, empty),
  same `_make_bare_module`/explicit `delete(Module)`-after-test cleanup
  discipline.
- Verified via the full backend pytest (778 passed, up from 774, 100%
  coverage maintained) -- no frontend changes in this part.

**Phase 23: cross-module conflict detection round 6 -- widget.xml (recorded
2026-11-13):** part 3, closing out feature-search round 4. Confirmed zero
hits for `widget.xml`/`widget_xml`/`WidgetEntry` anywhere in
`app/scanner/` -- a genuinely unparsed Magento declarative-config file,
unlike parts 1-2 of this round which were detection-only additions on data
already scanned. `<widget id="...">` declarations are merged by Magento
into one table by id the same way `indexer.xml`'s `<indexer id="...">` is
-- same "plain duplicate-id" shape as `indexer_conflicts.py`, not the
"different value" shape part 1's virtualType check needed.

- No `area` column on `module_widgets`, deliberately contrasted with
  `module_routes` from the prior round: `routes.xml`'s route id/frontName
  uniqueness is genuinely scoped per area (frontend vs. adminhtml) by
  Magento's own routing design, but widget ids are a single global
  namespace regardless of which `view/{base,frontend,adminhtml}/widget.xml`
  file declared them -- so area isn't part of the conflict key here, and
  isn't stored at all (nothing would ever read it).
- Parses all three known view-dir locations
  (`view/base/widget.xml`/`view/frontend/widget.xml`/`view/adminhtml/widget.xml`)
  and flattens them into one list -- `view/base` is the common real-world
  location, the other two are rarer but valid per Magento's own merge rules,
  and since there's no area-scoping here, there's no reason to keep them
  separate the way `routes.xml` needed to.
- This is the first file this codebase reads from a module's `view/`
  directory at all (confirmed via grep: no `"view/base"`, `"view/frontend"`,
  or `"view/adminhtml"` path construction anywhere in `app/scanner/` before
  this) -- `view/` otherwise holds layout XML, templates, and UI component
  config this project has no reason to parse structurally.
- Because this is genuinely new scanning surface -- not just new detection
  logic on already-scanned data, unlike parts 1-2 -- it gets its own
  roadmap row (Phase 23 in CLAUDE.md's Phase plan table) and a README
  mention, matching every prior new-parser round; parts 1-2 stayed
  decision-log-only, same precedent as `find_similar_modules`/
  `get_module_history`/`get_module_findings` earlier this session.
- Test fixture: extended the existing `conflict-store` `Vendor_ConflictA`/
  `Vendor_ConflictB` with one `view/base/widget.xml` each, declaring the
  same `<widget id="conflict_shared_widget">` -- same "extend, don't
  rebuild" pattern every prior conflict-detection round used.
- Verified via the full backend pytest (788 passed, up from 778, 100%
  coverage maintained) and frontend `tsc`/`eslint`/`vitest` (254 passed).
  Full real-stack `.env`-swap/Playwright verification for all three parts
  of this round runs once, after this part, per the approved plan.

**Optional bundled Ollama service, profile-gated (recorded 2026-11-13):**
raised by the user after the "running fully local" README section shipped
-- "why does someone need to install Ollama on the host themselves, isn't
the whole point of docker-compose that it's all one command?" Real
tradeoff, not just friction: Ollama **inside a container loses GPU access
on Mac/Windows** (Docker Desktop can't reach Apple Metal), so a plain
always-on `ollama` service in the default `up` would silently make the
free/local AI path painfully slow for most desktop users, while install-
natively keeps GPU acceleration. Resolved as two explicit paths rather
than picking one:

- Path A: `ollama` added to `docker-compose.yml` under `profiles:
  ["local-ai"]` (`docker compose --profile local-ai up -d`, or `make
  up-local-ai`) -- zero host install, CPU-only on Mac/Windows, fine for
  Linux-with-GPU-passthrough-already-set-up or just trying it out. Not
  part of the default `up` -- bundling multi-GB model weights into every
  first `docker compose up` would make the normal, AI-less-by-default path
  slow and heavy for no reason.
- Path B: native host install (the original README instructions), which
  keeps GPU acceleration on Mac/Windows and whatever GPU passthrough
  Linux users already have.
- `OLLAMA_BASE_URL` differs by path (`http://ollama:11434` vs.
  `http://host.docker.internal:11434`) -- both documented side by side in
  `.env.example` and the README rather than silently picking one.
- Verified for real: brought the bundled `ollama` container up with the
  real `.env` safely swapped out first (same protocol as every real-stack
  verification this session), confirmed `GET /api/tags` responds
  (`{"models":[]}`, no models pulled -- didn't pull the real multi-GB
  models just to prove the container starts and is reachable), then tore
  it down and removed the now-unused `ollama_data` volume before restoring
  the real `.env`.

**GitHub Deployments tracking wired to the real deploy job (recorded
2026-11-13):** the user noticed GitHub's own Deployments tab
(repos/.../deployments) showed exactly one entry, ever -- created
2026-11-10 by Fly.io's own GitHub App integration on what was apparently
the very first deploy, permanently stuck on "failure" even though that
same commit's real `Deploy to Fly.io` CI job succeeded (confirmed via `gh
run view`), and never updated again despite many real successful deploys
since (`gh api repos/.../deployments --jq length` stayed at 1 through a
brand-new, verified-live deploy). Root cause: `flyctl deploy` itself never
calls GitHub's Deployments API at all -- that one entry was a one-time
side effect of Fly's GitHub App detecting the app, not something the CI
job ever drove.

Fixed by having the `deploy` job in `ci.yml` own its own GitHub Deployment
record directly via `gh api` (no third-party Action) -- one deployment
created per CI run (`environment: "production"`, `required_contexts: []`
to skip GitHub's legacy commit-status gating, since readiness is already
enforced by the job's own `needs:`), posted `in_progress` before
`flyctl deploy` runs, then `success`/`failure` after both the api and web
deploys finish (`if: always()`, keyed off `steps.deploy_api.outcome`/
`steps.deploy_web.outcome`) -- one combined status for both Fly apps,
not two separate deployment records, since they deploy together as one
release. Needed `deployments: write` added to the job's `permissions:`.

Cleaning up the old stale "failure" entry (mark `inactive`, then delete)
needed a `gh api` write call that the harness's auto-mode classifier
blocked as an "External System Writes" action -- left for the user to
run themselves rather than worked around.

**Phase 24: lightweight access gate on write/cost-incurring endpoints
(recorded 2026-11-13):** the project's own roadmap note (`docs/v1-port-
roadmap.md`, written when Phase 13 was scoped) had explicitly flagged this
as owed once the public demo existed: "worth a lightweight access gate
(not full OAuth) when the public demo actually starts." Confirmed before
writing anything that the live Fly.io demo has no active budget leak today
(README: no LLM key/scan root configured there), so this is a genuine
prerequisite for a future "turn on a real key on the public demo" step,
not a fix for an active incident.

- Scope was deliberately narrow: one shared secret
  (`WRITE_ACCESS_TOKEN`, empty = disabled, same convention as
  `WEBHOOK_HMAC_SECRET`/`ALERT_WEBHOOK_URL`) gating only the handful of
  endpoints that cost money or mutate shared global state -- `POST /chat`,
  `PATCH /settings/llm`, `POST /scan`/`POST /scan/stream`. All read-only
  browsing (module list/detail, search, stats, `GET /settings/llm`) stays
  open, since the whole point of a public portfolio demo is that visitors
  can browse the already-scanned data freely.
- The real motivating risk turned out to be broader than "chat costs
  money": `PATCH /settings/llm` mutates the single shared `RuntimeLlmConfig`
  row every visitor's session reads from -- once a real key exists, an
  unauthenticated caller could already redirect it to an attacker's
  `llm_api_base` (a prior, separately-fixed security bug noted elsewhere in
  this log) without this gate. Protecting that route was treated as equally
  important as protecting `/chat` itself, not an afterthought.
- `backend/app/api/auth.py`'s `require_write_access` reuses the exact
  `hmac.compare_digest` primitive `webhooks.py`'s HMAC check already
  established, applied via FastAPI's `dependencies=[Depends(...)]` route
  parameter (not a body check) so it runs before the route body does any
  work. Deliberately a no-op whenever the token is unset -- every existing
  local/self-hosted `docker compose up` user's behavior is unchanged.
- Explicitly rejected a login page, sessions/cookies, or per-user accounts
  -- CLAUDE.md already states a blanket auth layer is a bigger
  architectural decision than this single-user tool needs; a single shared
  secret an operator hands out alongside the demo link is the right size
  for "keep random bots and drive-by visitors from burning the budget," not
  "support multiple distinct identities."
- Frontend: `frontend/lib/access-token.ts`'s `getStoredAccessToken`/
  `setStoredAccessToken` wrap `localStorage` (try/catch, same defensive
  pattern this project's other browser-storage reads already use).
  `apiFetch`/`streamSse` attach the stored token as `X-Access-Token`
  automatically and throw a dedicated `AccessTokenRequiredError` on a 401
  instead of the generic "API responded with 401" both already fell back
  to, letting each page tell "needs a token" apart from every other
  failure. A new shared `<AccessTokenPrompt>` component (inline input +
  button, matching this app's existing convention of plain inline error
  text rather than a modal -- no modal/dialog system exists anywhere else
  in this codebase for anything but the onboarding wizard) is wired into
  the three call sites that hit a gated route: chat send, the settings
  PATCH mutation (retried via TanStack Query's own retained
  `mutation.variables`, not a separately-tracked ref), and the Modules
  page's scan trigger.
- Verified: new backend tests (`tests/api/test_access_gate.py`, mirroring
  `test_webhooks_scan.py`'s shape) plus the full backend suite (799
  passed, 2 skipped) with no regression on the now-gated routes' own
  existing tests; full frontend suite (265 passed) including new
  prompt-and-retry coverage in `chat`/`settings`/`modules` page tests and
  the `api.ts`/`sse.ts`/`access-token.ts` unit tests; `ruff`/`mypy`/`tsc`/
  `eslint` all clean. No real-stack `docker compose`/Playwright pass this
  round -- this phase has no new Playwright-relevant user journey (the
  gate is off by default in every e2e environment, matching every real
  local/self-hosted deployment too), so the lighter backend+frontend-unit-
  test verification already used for schema-only phases (e.g. Phase 20)
  was judged sufficient.
- **Correction to this same session's own research**: the candidate list
  presented to the user alongside this one included "CSV export of the
  module/report table" as a missing feature, based on a `grep -rli export
  frontend/src` that returned nothing -- `frontend/src` doesn't exist in
  this repo (the real root is `frontend/app`/`frontend/lib`/
  `frontend/components`); CSV export already shipped (`frontend/lib/csv.ts`,
  wired into the Modules page's "Export CSV" button). Caught only once
  actually reading `modules/page.tsx`'s real imports while wiring this
  phase's scan-trigger gate -- a reminder that a path-based absence check
  is only as good as the path being right, not a substitute for actually
  opening the file.

**Phase 25: cross-module conflict detection round 7 -- menu.xml/cache.xml
(recorded 2026-11-13):** candidate C from this session's "next phase"
round, continuing the established family (Phases 15/19/20/22/23). Schema
for both files confirmed via web research first, since no real example of
either exists anywhere in this repo (same situation Phase 20's indexer.xml/
mview.xml round was in) -- menu.xml's `id` attribute is a **confirmed hard
Magento error** on duplicate ("Two 'add' commands cannot have equal id"),
while cache.xml's `name` attribute follows the usual silent-override
pattern (a module legitimately re-declaring a core cache type's cosmetic
attributes is real and intentional).

- **Severity decision, confirmed with the user before coding**: despite
  menu.xml's duplicate-id conflict being a guaranteed install/compile
  failure -- a different class of certainty than every other check in this
  family, which are all ambiguous silent-override risks -- `menu_item_id_conflict`
  was kept severity `warning`, not given a one-off `blocking` tier. Matches
  the existing `circular_dependency` precedent (Phase 15): also a
  guaranteed break, also deliberately kept `warning` for consistency with
  the rest of the cross-module-conflict family, which has no `blocking`
  gate concept of its own.
- **`cache_type_conflict` only fires on a real `instance` disagreement**,
  not a plain duplicate-name shape like every other check in this family
  (`widget_id_conflict`/`indexer_id_conflict`/etc.) -- same "different value
  for the same key" shape as `preference_conflict`. A module that
  re-declares the same cache type name without setting `instance` at all
  (only overriding `<label>`/`<description>`) is never itself a
  disagreement; only distinct, non-null `instance` values across 2+
  modules count. This is deliberately the second check in the family (after
  `preference_conflict`) to need this shape rather than `widget_conflicts.py`'s
  plain "any duplicate id" template.
- Pure new-parser-plus-detection addition, same `_sync_module_children`/
  Phase-C pattern as every prior round -- two new tables (`module_menu_items`,
  `module_cache_types`), two new migrations (table creation, then check_type
  constraint update, mirroring the Phase 20 indexer+mview precedent of
  landing two tables in one migration and two check_types in the next,
  rather than four separate migrations).
- Verified with the full real-stack discipline this family's fixture-
  touching rounds use (Phase 22/23's rigor, not Phase 20's lighter path):
  a real `alembic downgrade -2`/`upgrade head` round-trip against a live
  Postgres; the `.env`-swap-to-local-docker protocol (confirmed with the
  user first, since this machine's real `.env` points at the live
  production Neon demo database) -- backed up to the scratchpad, replaced
  with a safe all-local version using the canonical, correctly-cased
  `/Users/michalper/Projects/magewiki/...` fixture paths (not the
  lowercase `/Users/michalper/projects/magewiki` alias also present on this
  machine, which the Phase 21 case-sensitivity incident already showed
  produces duplicate rows for what's semantically the same path); a real
  `docker compose up -d --build` (only `migrate` structurally needed the
  rebuild -- `api`/`worker`/`web` all bind-mount their source and hot-reload,
  confirmed via `GET /health` reporting `schema: "ok"` at revision `0046`
  before testing); full Playwright (33/33, up from 32) and full backend
  pytest (823 passed, up from 799) green; then the real `.env` restored
  from the scratchpad backup and diffed byte-for-byte (identical MD5)
  before finishing.

**Phase 26: surface 6 orphaned fact types + 2 missing agent tools (recorded
2026-11-14):** closes both remaining candidates from this session's "co
dalej?" research pass (candidate 1, the strongest finding, and candidate
2). Pure exposure work -- no new parser, no schema change, no migration.

- `acl_resources`/`ModuleIndexer`/`ModuleMview`/`ModuleRoute`/`ModuleWidget`/
  `ModuleMenuItem`/`ModuleCacheType` (Phases 19/20/22/23/25) were parsed and
  persisted purely for fleet-wide conflict detection -- never reaching the
  AI synthesis prompt or `ModuleDetail`, unlike every other structural fact
  type since Phase 14. Added all 7 to `ModuleFacts`/`gather_module_facts()`
  (`app/analyzer/facts.py`), to `build_module_synthesis_prompt()`
  (`app/analyzer/prompts.py`, one new human-readable block per type, same
  terse bullet style as every existing block), and to `ModuleDetail`/
  `get_module()` (`app/api/routes/modules.py`, 7 new `XSummary` models +
  `model_validate(..., from_attributes=True)`, the exact existing pattern).
  Confirmed no frontend change was needed before touching anything:
  `ModuleDetailClient.tsx` renders every `ModuleDetail` field generically
  through AI-written README prose (only Plugins/Observers/Configuration get
  a dedicated card) -- new fields fall through to prose with zero UI work,
  matching the Phase 14 precedent exactly.
- `get_module_dependency_graph`/`find_duplicate_module_pairs` wrap the
  existing `GET /modules/{id}/graph` and `GET /modules/duplicate-pairs`
  REST endpoints as chat-agent tools -- the same gap class
  `find_similar_modules`/`get_module_history`/`get_module_findings` closed
  earlier this session. The dependency-graph route function has no
  separate query-layer helper (its BFS logic is inline in the route) and
  takes `(module_id, depth, session)` as plain arguments -- `@router.get`
  returns the function unchanged, so the tool wrapper imports and calls it
  directly (aliased `_get_module_dependency_graph`) rather than duplicating
  ~170 lines of BFS logic. `find_duplicate_module_pairs` is fleet-wide (no
  `module_id`) and returns a plain list, same no-found-flag shape as
  `list_modules`.
- Regenerated `frontend/lib/api-types.ts` **without touching the real
  `.env`** (this machine's `.env` points at the live production Neon demo):
  ran the API directly with `DATABASE_URL`/`REDIS_URL` passed as explicit
  process env vars (overriding whatever `.env` has, the same override
  trick already used for every `pytest` invocation this session) against
  local `db`/`redis` containers, instead of a full `docker compose up`.
  Confirmed the resulting diff touched only the 7 new summary types and
  their `ModuleDetail` fields before committing.
- Verified: 5 new/extended backend tests (49 passed in the touched files,
  828 passed full suite, up from 823) plus `ruff`/`mypy` clean; frontend
  `tsc`/`eslint`/`vitest` (265 passed, unchanged -- nothing references the
  new fields yet) clean. No migration, no real-stack Playwright run needed
  -- no new scanning behavior, no new UI/e2e-visible journey.

**Docs-freshness pass: README conflict-check list + screenshots refreshed
(recorded 2026-11-14):** a "what's next" research round found two genuine,
self-flagged gaps rather than any new feature scope. (1) README's
"Cross-module conflict detection" section said "these fifteen" and
listed 15 bullets, but the real `CHECK_TYPES` list had grown to 17
fleet-wide conflict check_types since Phase 19 first flagged this exact
section as going stale -- missing `menu_item_id_conflict`/
`cache_type_conflict` (Phase 25) entirely. Fixed the count and added both
bullets. Also found and fixed a second, bigger gap the research pass
itself didn't check: the README's own `[x] Phase N` checklist stopped at
Phase 23 -- Phases 24 and 25 (both real, numbered CLAUDE.md phases) were
missing rows; added them. (Phase 26 stayed decision-log-only, matching
how the earlier `find_similar_modules`-tool/duplicate-pairs-view additions
were never added to this checklist either -- the checklist's own
convention is numbered phases only.)

(2) `docs/screenshots/modules.jpg`/`stats.jpg` were last captured
2026-11-10, predating Phases 19-26 -- missing the newer conflict badges,
the Phase 21 similar-modules/compare additions, and the Phase 22b
fleet-trend chart. Recaptured against a real, running local stack, same
`.env`-swap-to-local-docker protocol as every real-stack verification
this session (backed up to the scratchpad, replaced with a safe local
version pointing both scan roots at the committed `demo-store`/
`conflict-store` fixtures, restored and diffed byte-for-byte afterward).
Seeded via the same `POST /scan` + `packagist_cache`-seeding calls
`global-setup.ts` already uses for e2e, then captured via
`claude-in-chrome` rather than Playwright (a one-off capture task, not a
repeatable test). The resulting `modules.jpg` is admittedly busier than
the original (Vendor_ConflictA alone carries ~20 badges, since the
conflict-store fixture is deliberately dense to exercise every check) --
accepted as a fair tradeoff: this is the same safe, already-approved test
data this project uses everywhere else, and a screenshot showing real
depth of checks is a reasonable thing for a portfolio project to show off,
not a defect to fix.

Also updated CLAUDE.md's own Working Method section per an explicit user
request mid-session: "every new feature needs both 100% unit-test coverage
and real e2e coverage" -- strengthens the existing "require tests alongside
code" bullet from a vague requirement into the two concrete bars this
project has in fact been holding itself to since the 100%-coverage-in-CI
decision (`codecov.yml`) and the per-phase Playwright-coverage discipline,
making both an explicit, standing rule rather than something a future
session would need to re-derive from precedent alone.

**README: real PHPUnit coverage screenshot + a stale phase-count fix
(recorded 2026-11-14):** the user asked, after confirming the real
PHPUnit-execution feature already existed, to also put it in the
screenshots -- the README's Screenshots section had four images (modules,
stats, graph, chat) but no module-detail view at all, so the "1/N tests
failed · N% coverage" badge was never actually shown anywhere. Used the
real `Ordo_Automation` fixture (CLAUDE.md's own approved public test
data, at `/Users/michalper/Projects/magento-ordo-test/vendor-src-sync`)
rather than a committed synthetic fixture, for the same reason the Wiki's
own screenshots already use it -- a real 1515-class, 3013-test module is a
far more convincing demonstration than a toy fixture. Same `.env`-swap-
to-local-docker protocol as every other real-stack capture this session
(backed up, replaced with a safe local version pointing
`MAGEWIKI_SCAN_ROOT_1` at the Ordo fixture, local `db`/`redis` only, no
LLM key); the real scan took ~4 minutes (1515 classes, full PHPStan/
PHPMD/phpcs/Rector/PHPUnit against a real module) and came back with
3013 tests run, 1 failed, 96.94% coverage -- consistent with the
decision log's own earlier-recorded numbers for this same fixture. New
`docs/screenshots/module-detail.jpg`, with a new row in the README's
Screenshots section. `.env` restored from the backup and diffed
byte-for-byte afterward, same as every prior round.

Also fixed, found while editing the same section: the README's own
"Project status" line still said "all 24 planned phases done (0–12b,
13–23)", unsynced since Phase 23 despite the Roadmap checklist right
below it already listing through Phase 25 (fixed in the earlier
docs-freshness pass). Updated to "26 planned phases... (0–12b, 13–25)"
and added the Phase 24/25 achievements to the same sentence.
