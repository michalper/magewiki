# MageWiki-AI

![CI](https://github.com/michalper/magewiki/actions/workflows/ci.yml/badge.svg)
[![codecov](https://codecov.io/gh/michalper/magewiki/branch/main/graph/badge.svg)](https://codecov.io/gh/michalper/magewiki)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.13-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.162-009688?logo=fastapi&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?logo=postgresql&logoColor=white)
![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-Kustomize-326CE5?logo=kubernetes&logoColor=white)

An AI-powered catalog and chat agent for Magento 2 codebases. MageWiki-AI scans Magento modules (`module.xml`, `composer.json`, `di.xml`, `events.xml`, `Plugin/` classes), builds a knowledge base in PostgreSQL, and lets developers and PMs ask natural-language questions about the architecture — with every answer citing the module and file it came from. It also runs a battery of quality, security, and Magento-upgrade-readiness checks on every scanned module and surfaces the results as badges, a stats dashboard, and a multi-repo fleet view.

Project status: **Phases 0–12b and 14 done** (only Phase 13, cloud deployment, is deferred) — the MVP (v1.0, Phases 0–5) plus cron/webhook automation, BYOK in the UI, Ollama support, a per-module dependency graph, an evaluation suite, CI/CD, a local Kubernetes deployment, parser-only quality checks, CVE/dependency intelligence, a multi-repo fleet view, a real PHP static-analysis toolchain (PHPStan/PHPMD/phpcs/Rector), Magento-upgrade-readiness checking, and deeper structural facts (webapi/crontab/db_schema/system.xml). See [Roadmap](#roadmap) below and `CLAUDE.md` for the full design, including the recorded decision behind each phase.

**[See the full Wiki](https://github.com/michalper/magewiki/wiki)** for a screen-by-screen walkthrough — every screenshot there is a real scan of [Ordo_Automation](https://github.com/michalper/ordo), not a synthetic demo.

## Screenshots

| Modules | Stats |
|---|---|
| ![Modules list](docs/screenshots/modules.jpg) | ![Stats dashboard](docs/screenshots/stats.jpg) |

| Dependency graph | Chat |
|---|---|
| ![Dependency graph](docs/screenshots/graph.jpg) | ![Chat](docs/screenshots/chat.jpg) |

## Stack

- Backend: Python, FastAPI, async SQLAlchemy, Alembic
- Database: PostgreSQL + pgvector, tsvector, pg_trgm
- Frontend: Next.js (App Router), TypeScript, Tailwind, shadcn/ui, TanStack Query
- Queue: ARQ + Redis (nightly rescan cron + a daily Magento-release-cache refresh cron)
- LLM: LiteLLM (BYOK — Anthropic Claude for now, DeepSeek/Ollama supported; see `CLAUDE.md`)
- PHP static analysis: a dedicated `php-analyzer` sidecar (plain PHP, no framework) running PHPStan, PHPMD, phpcs, and Rector against scanned modules, reachable only on the internal Docker network

Full architecture and phase plan: see `CLAUDE.md`.

## What the AI is for, what it costs, and why you need an API key

MageWiki-AI's **scanner is 100% free and local** — module discovery, every
XML/composer/PHP parser, the dependency graph, and the entire PHPStan/PHPMD/
phpcs/Rector + CVE/abandoned-dependency/Magento-upgrade-readiness quality
toolchain run with no AI involved and no API key at all. You can `docker
compose up` with every key left blank and still get a fully populated
Modules/Stats/Repos UI, a dependency graph, and every quality badge — the AI
only adds two things on top of that:

1. **Per-module documentation** (the README tab on a module's page: summary,
   features, integrations, risks, PM/dev write-ups) — an LLM call per
   changed file, plus one per module to synthesize them together.
2. **The chat agent** (natural-language Q&A with citations) — an LLM call
   per message, plus a one-time embeddings call per analyzed file/chunk so
   the agent's hybrid search has something to retrieve from.

Both call a real, paid third-party API via [LiteLLM](https://docs.litellm.ai/)
(BYOK — bring your own key, no shared/free tier bundled with this project),
which is why `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` exist in `.env.example`:
Anthropic Claude for the two write-ups above and the chat agent, OpenAI for
embeddings. Leave both blank to run the free, AI-less half of the product;
add them (and optionally lower `LLM_MONTHLY_BUDGET_USD`, default $20) when
you want generated docs and chat. DeepSeek/Ollama are wired as dormant,
cheaper/local BYOK alternatives to Anthropic — see `CLAUDE.md`.

Measured against a real 760-module Magento store (not a synthetic benchmark):

| Step | Model | Cost |
|---|---|---|
| Per-file summary | `anthropic/claude-haiku-5-5` | ~$0.002/file |
| Module synthesis | `anthropic/claude-haiku-5-5` | ~$0.002/module |
| Module synthesis | `anthropic/claude-sonnet-5-5` (optional `SYNTHESIS_MODEL` override — see CLAUDE.md) | ~$0.08/module |
| Embeddings | `openai/text-embedding-3-small` | ~$0.02/million tokens (negligible per module) |
| Chat | whatever `LLM_MODEL` is configured | one LLM call per message, same budget pool as the above — no separate figure measured yet |

Haiku is the default everywhere — cheap, and reliable enough for per-file summaries.
At real fleet scale it fails module-level synthesis validation on a meaningful
share of modules (a much larger, stricter JSON object than a file summary); the
optional `SYNTHESIS_MODEL` override trades ~40x the per-module cost for
materially higher reliability on that one step only. For the full 760-module
store, a one-time full-fleet synthesis backfill on Sonnet cost roughly **$30**
total — budget accordingly if you enable the override on a large existing
store rather than a fresh/incremental scan (which only re-synthesizes modules
whose files actually changed, so ongoing cost is far lower than a backfill).

`LLM_MONTHLY_BUDGET_USD` is a hard safety cap, not just an estimate: every AI
call checks spend-so-far first, and once the cap is hit, affected modules move
to a `paused_budget` state (visible on the Modules page) instead of silently
continuing to spend — see `CLAUDE.md`'s "Scan, cron, and cost control" for how
it's enforced and how to resume paused modules once you raise it.

## Roadmap

- [x] **Phase 0** — Repo skeleton, docker-compose, migrations
- [x] **Phase 1** — Scanner: module discovery, XML/composer/PHP parsers, saved to the DB
- [x] **Phase 2** — Per-file hash, diff, module state machine, ARQ+Redis queue
- [x] **Phase 3** — AI analysis: JSON schema, tag dictionary, cache, cost tracking, budget, README from the DB
- [x] **Phase 4** — Embeddings and hybrid retriever (vector + FTS + trigram, RRF)
- [x] **Phase 5** — Agent with tools, SSE chat, citations, pm/dev modes
- [x] **Phase 6** — Cron, HMAC webhook, BYOK in the UI, Ollama, dependency graph
- [x] **Phase 7** — Evaluation suite (recall@k, MRR, negative/enumeration questions)
- [x] **Phase 7b** — CI/CD (GitHub Actions): lint, tests, Docker build, and the PR-comment RAG eval all verified green
- [x] **Phase 8** — Kubernetes: Kustomize manifests, scan CronJob, verified end-to-end on a local `kind` cluster
- [x] **Phase 9** — Parser-only quality checks (composer completeness, `@deprecated`, hardcoded secrets, test presence) + badge/KPI-ring UI foundation
- [x] **Phase 10** — Dependency intelligence: CVE/security-advisory check + abandoned/outdated check
- [x] **Phase 11** — Multi-repo fleet view
- [x] **Phase 12** — PHP static-analysis toolchain (PHPStan/PHPMD/phpcs/Rector)
- [x] **Phase 12b** — Magento upgrade readiness: PHP-version and `magento/*` dependency compatibility against the latest Magento release, refreshed via a daily cron
- [ ] **Phase 13** — Cloud deployment (GCP/Azure via Terraform) — deferred, no cloud account/budget yet
- [x] **Phase 14** — Deeper structural facts: `webapi.xml`, `crontab.xml`, `db_schema.xml`, `system.xml`, `di.xml` `virtualType`, and message-queue topology (`communication.xml`/`queue_topology.xml`/`queue_consumer.xml`)

Full detail (done-criteria, data model, RAG design, and the decision recorded behind each phase) per phase: see `CLAUDE.md`.

## Evaluation

Retrieval quality measured against a real third-party module (`Ordo_Automation`,
B2B/B2C marketing automation, 840 files), with a real Anthropic synthesis pass and
real local Ollama embeddings (`bge-m3`) — not a synthetic fixture. recall@k = "at
least one correct chunk appeared in the top k results"; MRR = mean reciprocal rank of
the first correct hit. See `backend/app/evaluation/` for the question set, metrics,
and runner.

The suite is built and wired into CI (`7b`'s PR-comment check); the numbers below are
from a real run against this fixture. Regenerate them with:

```bash
docker compose exec api python -m app.evaluation.run_eval
```

This makes real Anthropic (synthesis) + embedding API calls — OpenAI
`text-embedding-3-small` by default (not free), or point `EMBEDDING_MODEL` at a local
Ollama model instead (`.env`, or the Settings page's BYOK override) to run at $0. The
$0 Ollama path has now been run end-to-end successfully (the table below is from that
run, `EMBEDDING_MODEL=ollama/bge-m3`, `EMBEDDING_DIMENSIONS=1024` — the embedding
vector's dimension is configurable per deployment, see CLAUDE.md's "Configurable
embedding dimension" decision note) — one honest caveat remains: these numbers measure
`bge-m3`, not OpenAI's embedding model, so they aren't directly comparable to a run
with `EMBEDDING_MODEL` left at its OpenAI default.

| Mode | recall@1 | recall@3 | recall@5 | recall@10 | MRR |
|---|---|---|---|---|---|
| Vector-only | 0.50 | 0.80 | 0.90 | 0.90 | 0.68 |
| FTS-only | 0.10 | 0.20 | 0.20 | 0.20 | 0.13 |
| Hybrid (RRF) | 0.50 | 0.90 | 0.90 | 0.90 | 0.68 |

Hybrid clearly beats FTS-only (which alone misses most relevant chunks on these
natural-language questions) and matches-or-beats vector-only at every k, confirming
the RRF fusion is pulling its weight rather than just adding complexity. Enumeration
questions (5/5) and negative/"not found" questions (3/3) also passed in full — the
agent correctly used SQL-backed tools for "how many" questions instead of relying on
lossy top-k retrieval, and correctly said "not found" rather than hallucinating when
asked about an integration (Klaviyo) the module doesn't have.

## Quickstart

```bash
make up
```

(or, without `make`: `cp .env.example .env && docker compose up -d`)

Migrations run automatically on every `up` — a dedicated `migrate` container
runs `alembic upgrade head` once and exits before `api`/`worker` start, so a
new version with a schema change can never run against a stale database.
`GET /health` reports `schema: "stale"` if a container ever does end up
running against an unmigrated database, instead of failing only on the
first real query.

- API health check: http://localhost:8000/health
- Web UI: http://localhost:3000

### Scan your own Magento store

1. On a fresh server/clone, set at least one `MAGEWIKI_SCAN_ROOT_1` (and
   optionally `_2`/`_3`) in `.env` to a host directory that contains the
   store(s)/module(s) you want to scan, then `docker compose up -d` again so
   the new bind mount takes effect. The Modules page's Scan box shows what's
   currently configured ("Scannable under: ...").
2. Open http://localhost:3000/modules, paste the absolute path to a Magento
   store or a single module (must be under a configured scan root) into the
   Scan box, and click **Scan**.
3. If something fails, check the warnings shown under the scan result first —
   every per-module failure is reported there, not just a silent module
   count — before checking `docker compose logs api`.

### Running tests

```bash
docker compose exec api pytest tests/ -v
```

Tests run against their own `magewiki_test` database, dropped and recreated
fresh every run, and their own Redis logical database (index 15) flushed fresh
every run — never the ones the running `api`/`worker` containers use, so
running tests never affects an environment you're also actively scanning
with, and a real queued job never races against a test's own ARQ queue
assertions. This is set up automatically (`tests/conftest.py` redirects
`DATABASE_URL`/`REDIS_URL`); no separate migration or setup step is needed
just for tests.

## Kubernetes (local)

Plain Kustomize manifests (no Helm) in `k8s/`: `base/` has the full workload set
(Postgres, Redis, api, worker, web, php-analyzer, a one-shot migration `Job`, and a
`CronJob` that scans the committed `tests/fixtures/demo-store` fixture nightly —
additive to the app's own internal ARQ cron in the worker process);
`overlays/kind/` patches the api/web Services to `NodePort` for local access
and provides the `kind` cluster's port mapping.

```bash
brew install kind   # if not already installed
kind create cluster --name magewiki --config k8s/overlays/kind/kind-config.yaml

docker build -t magewiki-backend:dev ./backend
docker build -t magewiki-frontend:dev ./frontend
kind load docker-image magewiki-backend:dev --name magewiki
kind load docker-image magewiki-frontend:dev --name magewiki

cp k8s/base/.env.k8s.example k8s/base/.env.k8s   # fill in; gitignored

kubectl apply -k k8s/overlays/kind
kubectl wait --for=condition=complete job/migrate -n magewiki --timeout=120s
kubectl rollout restart deployment/api deployment/worker -n magewiki
kubectl wait --for=condition=available deployment/api deployment/worker deployment/web -n magewiki --timeout=120s
```

- API: http://localhost:8080/health — Web UI: http://localhost:3080
- Trigger the scan CronJob on demand: `kubectl create job --from=cronjob/scan-demo-store manual-test -n magewiki`
- Teardown: `kind delete cluster --name magewiki`

## License

MIT — see `LICENSE`.
