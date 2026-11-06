# MageWiki-AI

![CI](https://github.com/michalper/magewiki/actions/workflows/ci.yml/badge.svg)

An AI-powered catalog and chat agent for Magento 2 codebases. MageWiki-AI scans Magento modules (`module.xml`, `composer.json`, `di.xml`, `events.xml`, `Plugin/` classes), builds a knowledge base in PostgreSQL, and lets developers and PMs ask natural-language questions about the architecture — with every answer citing the module and file it came from.

Project status: **Phases 0–7 done** (Phase 7's demo GIF still pending). MVP (v1.0, Phases 0–5) plus cron/webhook automation, BYOK in the UI, a working Ollama option, a per-module dependency graph, and an evaluation suite. See [Roadmap](#roadmap) below and `CLAUDE.md` for the full design.

## Stack

- Backend: Python, FastAPI, async SQLAlchemy, Alembic
- Database: PostgreSQL + pgvector, tsvector, pg_trgm
- Frontend: Next.js (App Router), TypeScript, Tailwind, shadcn/ui, TanStack Query
- Queue: ARQ + Redis
- LLM: LiteLLM (BYOK — Anthropic Claude for now, DeepSeek/Ollama supported; see `CLAUDE.md`)

Full architecture and phase plan: see `CLAUDE.md`.

## Roadmap

- [x] **Phase 0** — Repo skeleton, docker-compose, migrations
- [x] **Phase 1** — Scanner: module discovery, XML/composer/PHP parsers, saved to the DB
- [x] **Phase 2** — Per-file hash, diff, module state machine, ARQ+Redis queue
- [x] **Phase 3** — AI analysis: JSON schema, tag dictionary, cache, cost tracking, budget, README from the DB
- [x] **Phase 4** — Embeddings and hybrid retriever (vector + FTS + trigram, RRF)
- [x] **Phase 5** — Agent with tools, SSE chat, citations, pm/dev modes
- [x] **Phase 6** — Cron, HMAC webhook, BYOK in the UI, Ollama, dependency graph
- [ ] **Phase 7** — Evaluation suite (done), README updated, GIF recording still pending
- [x] **Phase 7b** — CI/CD (GitHub Actions): lint, tests, Docker build, and the PR-comment RAG eval all verified green
- [ ] **Phase 8** — Kubernetes
- [ ] **Phase 9** — Cloud deployment

Full detail (done-criteria, data model, RAG design) per phase: see `CLAUDE.md`.

## Evaluation

Retrieval quality measured against a real third-party module (`Ordo_Automation`,
B2B/B2C marketing automation), with real OpenAI embeddings and a real Anthropic
synthesis pass — not a synthetic fixture. recall@k = "at least one correct chunk
appeared in the top k results"; MRR = mean reciprocal rank of the first correct hit.
See `backend/app/evaluation/` for the question set, metrics, and runner; raw JSON at
`backend/app/evaluation/report/eval_report.json`.

| Mode | recall@1 | recall@3 | recall@5 | recall@10 | MRR |
|---|---|---|---|---|---|
| Vector-only | TBD | TBD | TBD | TBD | TBD |
| FTS-only | TBD | TBD | TBD | TBD | TBD |
| Hybrid (RRF) | TBD | TBD | TBD | TBD | TBD |

Enumeration (5/5) and negative/"not found" (3/3) question sets: see the JSON report
for pass/fail detail per question.

Regenerate these numbers:

```bash
docker compose exec api python -m app.evaluation.run_eval
```

<!-- TODO: record demo GIF -->

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
