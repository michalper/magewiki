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

To run it at $0, point `EMBEDDING_MODEL`/`LLM_MODEL` at a local Ollama model
instead (`.env`, or the Settings page's BYOK override — see
`app/runtime_config.py`'s `resolve_embedding_config`/`resolve_llm_config`,
which the eval runner already goes through, same as the main chat/analysis
path). Two honest caveats: the resulting recall@k/MRR numbers then measure a
different embedding model, not comparable to a real OpenAI-embeddings run;
and this specific path (Ollama + the evaluation suite specifically) hasn't
been run end-to-end yet, only the main chat/analysis BYOK path has.

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

Tests run against the **same** database the `api`/`worker` containers use —
there's no separate, disposable test database. Expect state changes (and
occasional cross-test flakiness from shared Postgres/Redis state) if you run
this against an environment you're also actively scanning with. Run
migrations (above) before running tests on a fresh database, or most of the
suite will fail with "relation does not exist" errors.

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
