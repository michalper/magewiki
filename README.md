# MageWiki-AI

An AI-powered catalog and chat agent for Magento 2 codebases. MageWiki-AI scans Magento modules (`module.xml`, `composer.json`, `di.xml`, `events.xml`, `Plugin/` classes), builds a knowledge base in PostgreSQL, and lets developers and PMs ask natural-language questions about the architecture — with every answer citing the module and file it came from.

Project status: **Phase 0 — project skeleton.** No scanning, AI, or RAG yet; see `CLAUDE.md` for the full phase plan.

## Stack

- Backend: Python, FastAPI, async SQLAlchemy, Alembic
- Database: PostgreSQL + pgvector, tsvector, pg_trgm
- Frontend: Next.js (App Router), TypeScript, Tailwind, shadcn/ui, TanStack Query
- Queue (from Phase 2): ARQ + Redis
- LLM (from Phase 3): LiteLLM (DeepSeek by default, BYOK)

Full architecture and phase plan: see `CLAUDE.md`.

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
