# MageWiki-AI

![CI](https://github.com/michalper/magewiki/actions/workflows/ci.yml/badge.svg)
[![codecov](https://codecov.io/gh/michalper/magewiki/branch/main/graph/badge.svg)](https://codecov.io/gh/michalper/magewiki)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.162-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?logo=postgresql&logoColor=white)

An AI-powered catalog and chat agent for Magento 2 codebases. MageWiki-AI scans Magento modules (`module.xml`, `composer.json`, `di.xml`, `events.xml`, `Plugin/` classes), builds a knowledge base in PostgreSQL, and lets developers and PMs ask natural-language questions about the architecture — with every answer citing the module and file it came from. It also runs a battery of quality, security, and Magento-upgrade-readiness checks on every scanned module and surfaces the results as badges, a stats dashboard, and a multi-repo fleet view.

Project status: **Phases 0–12b done** — the MVP (v1.0, Phases 0–5) plus cron/webhook automation, BYOK in the UI, Ollama support, a per-module dependency graph, an evaluation suite, CI/CD, a local Kubernetes deployment, parser-only quality checks, CVE/dependency intelligence, a multi-repo fleet view, a real PHP static-analysis toolchain (PHPStan/PHPMD/phpcs/Rector), and Magento-upgrade-readiness checking. See [Roadmap](#roadmap) below and `CLAUDE.md` for the full design, including the recorded decision behind each phase.

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
cp .env.example .env
docker compose build
docker compose up -d
docker compose exec api alembic upgrade head
```

The last step is required — the API container does **not** run migrations on
startup. Skipping it is the most common first-run issue: the app starts fine
(it doesn't touch the database until a request comes in), but every scan or
page load then fails because the tables don't exist yet.

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
