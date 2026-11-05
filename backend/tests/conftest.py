import os
import urllib.request
from pathlib import Path

import pytest
import pytest_asyncio

from app.config import settings
from app.db import async_session_factory


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


@pytest_asyncio.fixture
async def db_session():
    async with async_session_factory() as session:
        yield session
