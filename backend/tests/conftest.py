import os
import subprocess
import tempfile
import urllib.request
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

# Tests must never run against the same database the live api/worker
# containers use — a long-lived dev DB accumulates cross-run garbage (the
# confirmed cause of persistent analysis_cache/file_analyses FK-violation
# flakiness), and a real external user had his running webapp break after
# running pytest against his own dev stack. Redirect DATABASE_URL to a
# "_test"-suffixed sibling database *before* anything imports app.config/
# app.db — both build their engine/session factory once at import time, and
# other modules do `from app.db import async_session_factory` (binding their
# own local reference), so monkeypatching app.db's attributes afterwards
# would not reach code that already imported it. conftest.py is always
# pytest's first import, so this runs before any test module or app.* import
# has a chance to bind the wrong URL. Derived from whatever's actually
# configured (never hardcoded) so it's correct regardless of a developer's
# real POSTGRES_PASSWORD/POSTGRES_DB.
_REAL_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://magewiki:changeme@db:5432/magewiki"
)
_TEST_DATABASE_URL = _REAL_DATABASE_URL.rsplit("/", 1)[0] + "/" + _REAL_DATABASE_URL.rsplit("/", 1)[1] + "_test"
_TEST_DB_NAME = _TEST_DATABASE_URL.rsplit("/", 1)[1]
os.environ["DATABASE_URL"] = _TEST_DATABASE_URL

# Same reasoning as DATABASE_URL above, for Redis: tests and the live api/worker
# containers sharing one ARQ queue (redis://.../0) is the confirmed cause of
# test_queue_integration.py's long-standing flakiness — a real queued_jobs() check
# would race against the *actual* worker, which is always running in dev and picks
# up real jobs (including, sometimes, the exact job_id a test just enqueued) before
# the test gets to assert on it; real job IDs from a live user scan (e.g.
# "analyze:664:...") showed up in failure output more than once as proof. Redis
# supports 16 independent logical databases on one server with zero extra
# infrastructure — redirect to index 15 (last one, least likely to collide with any
# other logical use) instead of a real worker-shared index.
_REAL_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
_TEST_REDIS_URL = _REAL_REDIS_URL.rsplit("/", 1)[0] + "/15"
os.environ["REDIS_URL"] = _TEST_REDIS_URL

# POST /scan[/stream] (and the webhook equivalent) now enforce that `path` is under a
# configured scan root — a real access-control fix (see CLAUDE.md's security-review
# decision note), fixing a gap where that confinement was previously only UI text, never
# actually enforced. Tests that scan through the real HTTP endpoint use the repo's own
# tests/fixtures/ dir and pytest's tmp_path fixture (which lives under the system temp
# dir) — neither is a real deployment's configured MAGEWIKI_SCAN_ROOT_*, so explicitly
# widen scan roots for the test session to cover both, overriding whatever a
# developer's own .env happens to have set (tests must be deterministic regardless).
os.environ["MAGEWIKI_SCAN_ROOT_1"] = str(Path(__file__).parent.resolve())
os.environ["MAGEWIKI_SCAN_ROOT_2"] = tempfile.gettempdir()
os.environ["MAGEWIKI_SCAN_ROOT_3"] = ""

from app.analyzer.client import LlmCallResult
from app.analyzer.schemas import FileSummary
from app.config import settings
from app.db import async_session_factory
from app.models import Module
from app.scanner.orchestrator import scan_repository


def _ollama_reachable() -> bool:
    if not settings.ollama_base_url:
        return False
    try:
        urllib.request.urlopen(f"{settings.ollama_base_url}/api/tags", timeout=2)
        return True
    except OSError:
        return False

FIXTURES_DIR = Path(__file__).parent / "fixtures"

ORDO_FIXTURE_ENV = "MAGEWIKI_ORDO_FIXTURE_PATH"
MAGENTO_FIXTURE_ENV = "MAGEWIKI_MAGENTO_FIXTURE_PATH"

requires_ordo_fixture = pytest.mark.skipif(
    not os.environ.get(ORDO_FIXTURE_ENV) or not os.path.isdir(os.environ.get(ORDO_FIXTURE_ENV, "")),
    reason=f"set {ORDO_FIXTURE_ENV} to a real Ordo_Automation checkout to run this test",
)

requires_magento_fixture = pytest.mark.skipif(
    not os.environ.get(MAGENTO_FIXTURE_ENV) or not os.path.isdir(os.environ.get(MAGENTO_FIXTURE_ENV, "")),
    reason=f"set {MAGENTO_FIXTURE_ENV} to a real magento/magento2 checkout to run this test",
)

requires_anthropic_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="set ANTHROPIC_API_KEY to run tests that make real LLM calls",
)

requires_openai_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="set OPENAI_API_KEY to run tests that make real embedding calls",
)

requires_ollama = pytest.mark.skipif(
    not _ollama_reachable(),
    reason="set OLLAMA_BASE_URL to a reachable local Ollama server to run this test",
)


@pytest.fixture
def demo_store_path() -> Path:
    return FIXTURES_DIR / "demo-store"


@pytest.fixture
def demo_module_path(demo_store_path: Path) -> Path:
    return demo_store_path / "app" / "code" / "Vendor" / "Module"


# Plain importable helpers, not fixtures — every caller needs them with a
# specific session/path/suffix already in hand, which a fixture can't express
# as cleanly. Previously copy-pasted byte-for-byte into 9 different test
# files (tests/tasks/, tests/agent/, tests/search/, tests/scanner/,
# tests/analyzer/) — consolidated here, same import style already used for
# requires_ordo_fixture etc. elsewhere in this file.


async def delete_module_if_present(session, repo_root: str, name: str) -> None:
    existing = await session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == name))
    if existing is not None:
        await session.execute(delete(Module).where(Module.id == existing.id))
        await session.commit()


async def scan_demo_store(demo_store_path: Path, session, name: str = "Vendor_Module") -> Module:
    repo_root = str(demo_store_path.resolve())
    await delete_module_if_present(session, repo_root, name)
    await scan_repository(repo_root, session)
    return await session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == name))


def fake_summarize_file(call_log: list[str] | None = None):
    log = call_log if call_log is not None else []

    async def _fake(relative_path: str, content: str, **kwargs):
        log.append(relative_path)
        summary = FileSummary(file_summary=f"Summary of {relative_path}", notable_behavior=None)
        result = LlmCallResult(
            response_json=summary.model_dump(), tokens_in=100, tokens_out=20, cost_usd=Decimal("0.001")
        )
        return summary, result

    return _fake


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _test_database():
    """Drops and recreates the test database fresh for every pytest session,
    then migrates it — so flakiness from garbage left behind by a previous
    run is impossible by construction, same guarantee CI already gets from a
    brand-new Postgres service container every run. Connects with asyncpg
    directly against the *real* (already-existing) database to issue
    DROP/CREATE DATABASE — app.db's engine now points at the test DB, which
    doesn't exist yet at this point.
    """
    admin_url = _REAL_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(admin_url)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{_TEST_DB_NAME}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await conn.close()

    # Blocking by design: this is a one-time, session-scoped setup step that runs
    # before any concurrent async test work starts, so there's no event loop to
    # block for anyone but this fixture itself.
    subprocess.run(["alembic", "upgrade", "head"], check=True, env=os.environ)  # noqa: ASYNC221

    from app.tasks.queue import get_arq_pool

    pool = await get_arq_pool()
    await pool.flushdb()


@pytest_asyncio.fixture
async def db_session(_test_database):
    async with async_session_factory() as session:
        yield session
