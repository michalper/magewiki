# Contributing to MageWiki-AI

Thanks for considering a contribution. This is a portfolio project
(`michalper/magewiki`) maintained by one person, with no SLA on response
time — real contributions are still genuinely welcome.

## Setting up a dev environment

```sh
cp .env.example .env
docker compose up
```

That starts Postgres (with pgvector), Redis, the FastAPI backend, the
Next.js frontend, and runs migrations. See [README.md](README.md) for the
full walkthrough, including how to point a scan at a real Magento checkout.

## Code style and static analysis

- **Backend** (`backend/`, Python/FastAPI): `poetry run ruff check .` and
  `poetry run mypy app`.
- **Frontend** (`frontend/`, TypeScript/Next.js): `npm run lint`.

Both run in CI (`.github/workflows/ci.yml`) on every push/PR; a change that
doesn't pass either won't merge.

## Tests

- **Backend**: `poetry run pytest tests/ -v --cov=app --cov-report=xml`
  (`backend/`, from inside the dev container or a local Poetry env with the
  same Python version).
- **Frontend**: `npm run test:coverage` (`frontend/`).

Both are gated at **100% coverage** (lines/statements/functions; see
`codecov.yml`) — a new feature needs real tests alongside it, not a
follow-up PR. Prefer a real fixture under `backend/tests/fixtures/` over
mocking the thing you're actually testing (see `CLAUDE.md`'s own repeated
"a real X, not a mock" discipline).

## Security-relevant changes

Anything touching parsing of scanned-repo content (`backend/app/scanner/`),
file reads, or path handling: read `is_safe_to_read`'s own docstring in
`backend/app/scanner/discovery.py` first — this project treats a scanned
module's own files as untrusted input (see the project's security-fix
history in `.claude/skills/project-decision-log/SKILL.md`), and `backend/`
also has fuzz harnesses for exactly this surface
(`.clusterfuzzlite/fuzz_*.py`).

Found a vulnerability? See [SECURITY.md](SECURITY.md) — please don't open a
public issue for it.

## Architecture and decisions

[CLAUDE.md](CLAUDE.md) is the single source of truth for the data model, RAG
design, and phase plan; `.claude/skills/project-decision-log/SKILL.md` has
the dated history of *why* behind specific changes. Worth a skim before a
larger change, to avoid re-litigating something already settled.

## License

MIT — see [LICENSE](LICENSE). By contributing, you agree your contribution
is licensed under the same terms.
