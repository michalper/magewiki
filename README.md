# MageWiki-AI

An AI-powered catalog and chat agent for Magento 2 codebases. MageWiki-AI scans Magento modules (`module.xml`, `composer.json`, `di.xml`, `events.xml`, `Plugin/` classes), builds a knowledge base in PostgreSQL, and lets developers and PMs ask natural-language questions about the architecture — with every answer citing the module and file it came from.

Project status: **Phases 0–4 done** (skeleton, scanner, hash/diff + queue, AI analysis, embeddings + hybrid retriever). The chat agent is next. See [Roadmap](#roadmap) below and `CLAUDE.md` for the full design.

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
- [ ] **Phase 5** — Agent with tools, SSE chat, citations, pm/dev modes
- [ ] **Phase 6** — Cron, HMAC webhook, BYOK in the UI, Ollama, dependency graph
- [ ] **Phase 7** — Evaluation suite, README, GIF
- [ ] **Phase 7b** — CI/CD (GitHub Actions)
- [ ] **Phase 8** — Kubernetes
- [ ] **Phase 9** — Cloud deployment

Full detail (done-criteria, data model, RAG design) per phase: see `CLAUDE.md`.

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
