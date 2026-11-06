# MageWiki-AI

![CI](https://github.com/michalper/magewiki/actions/workflows/ci.yml/badge.svg)

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
B2B/B2C marketing automation), with real OpenAI embeddings and a real Anthropic
synthesis pass — not a synthetic fixture. recall@k = "at least one correct chunk
appeared in the top k results"; MRR = mean reciprocal rank of the first correct hit.
See `backend/app/evaluation/` for the question set, metrics, and runner.

The suite is built and wired into CI (`7b`'s PR-comment check), but hasn't been run
against this exact revision yet — the numbers below aren't filled in. Regenerate them
with:

```bash
docker compose exec api python -m app.evaluation.run_eval
```

This makes real OpenAI/Anthropic API calls (not free) and writes
`backend/app/evaluation/report/eval_report.json`.

| Mode | recall@1 | recall@3 | recall@5 | recall@10 | MRR |
|---|---|---|---|---|---|
| Vector-only | — | — | — | — | — |
| FTS-only | — | — | — | — | — |
| Hybrid (RRF) | — | — | — | — | — |

## Quickstart

```bash
cp .env.example .env
docker compose build
docker compose up -d
```

- API health check: http://localhost:8000/health
- Web UI: http://localhost:3000

Run backend tests:

```bash
docker compose run --rm api pytest tests/ -v
```

Run migrations:

```bash
docker compose run --rm api alembic upgrade head
```

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
