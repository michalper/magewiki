import os
import subprocess
import urllib.request
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

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

from app.config import settings  # noqa: E402 - must follow the DATABASE_URL redirect above
from app.db import async_session_factory  # noqa: E402 - ditto


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

    subprocess.run(["alembic", "upgrade", "head"], check=True, env=os.environ)


@pytest_asyncio.fixture
async def db_session(_test_database):
    async with async_session_factory() as session:
        yield session
