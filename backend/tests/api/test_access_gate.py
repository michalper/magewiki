from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session_factory
from app.main import app
from app.models import RuntimeLlmConfig
from tests.conftest import delete_module_if_present

TEST_TOKEN = "test-write-access-token"


@pytest.fixture(autouse=True)
def _configure_token(monkeypatch):
    monkeypatch.setattr(settings, "write_access_token", TEST_TOKEN)


@pytest.fixture(autouse=True)
async def _clear_runtime_config():
    async with async_session_factory() as session:
        await session.execute(delete(RuntimeLlmConfig))
        await session.commit()
    yield
    async with async_session_factory() as session:
        await session.execute(delete(RuntimeLlmConfig))
        await session.commit()


@pytest.mark.asyncio
async def test_chat_rejects_missing_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_rejects_wrong_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Access-Token": "wrong"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_accepts_correct_token(monkeypatch):
    async def fake_run_agent(session, messages, audience):
        yield {"event": "done", "usage": {}}

    monkeypatch.setattr("app.api.routes.chat.run_agent", fake_run_agent)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
            headers={"X-Access-Token": TEST_TOKEN},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_chat_allows_everyone_when_token_unset(monkeypatch):
    monkeypatch.setattr(settings, "write_access_token", "")

    async def fake_run_agent(session, messages, audience):
        yield {"event": "done", "usage": {}}

    monkeypatch.setattr("app.api.routes.chat.run_agent", fake_run_agent)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_settings_patch_rejects_missing_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/settings/llm", json={"llm_model": "anthropic/claude-haiku-5-5"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_settings_patch_accepts_correct_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            "/settings/llm",
            json={"llm_model": "anthropic/claude-haiku-5-5"},
            headers={"X-Access-Token": TEST_TOKEN},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_settings_get_stays_open_without_a_token():
    # Read-only browsing of the current config must not require the gate --
    # only the mutating PATCH does.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/settings/llm")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_scan_rejects_missing_token(demo_store_path: Path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/scan", json={"path": str(demo_store_path.resolve())})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_scan_accepts_correct_token(demo_store_path: Path, db_session: AsyncSession):
    await delete_module_if_present(db_session, str(demo_store_path.resolve()), "Vendor_Module")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/scan",
            json={"path": str(demo_store_path.resolve())},
            headers={"X-Access-Token": TEST_TOKEN},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_scan_stream_rejects_missing_token(demo_store_path: Path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/scan/stream", json={"path": str(demo_store_path.resolve())})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_modules_list_stays_open_without_a_token():
    # Read-only browsing of the catalog must not require the gate -- the
    # whole point of the public demo is that visitors can browse freely.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules")
    assert response.status_code == 200
