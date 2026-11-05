import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.config import settings
from app.db import async_session_factory
from app.main import app
from app.models import RuntimeLlmConfig


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
async def test_get_llm_settings_defaults_when_unconfigured():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/settings/llm")

    assert response.status_code == 200
    body = response.json()
    assert body["llm_model"] == settings.llm_model
    assert body["llm_key_configured"] is False
    assert body["embedding_model"] == settings.embedding_model
    assert body["embedding_key_configured"] is False


@pytest.mark.asyncio
async def test_patch_llm_settings_sets_model_and_key_without_echoing_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        patch_response = await client.patch(
            "/settings/llm", json={"llm_model": "deepseek/deepseek-chat", "llm_api_key": "sk-secret-value"}
        )
        get_response = await client.get("/settings/llm")

    assert patch_response.status_code == 200
    assert "sk-secret-value" not in patch_response.text
    patch_body = patch_response.json()
    assert patch_body["llm_model"] == "deepseek/deepseek-chat"
    assert patch_body["llm_key_configured"] is True

    get_body = get_response.json()
    assert get_body["llm_model"] == "deepseek/deepseek-chat"
    assert get_body["llm_key_configured"] is True
    assert "sk-secret-value" not in get_response.text


@pytest.mark.asyncio
async def test_patch_llm_settings_omitted_field_is_unchanged():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.patch("/settings/llm", json={"llm_model": "deepseek/deepseek-chat"})
        second = await client.patch("/settings/llm", json={"embedding_model": "openai/text-embedding-3-large"})

    assert second.status_code == 200
    body = second.json()
    assert body["llm_model"] == "deepseek/deepseek-chat"  # untouched by the second PATCH
    assert body["embedding_model"] == "openai/text-embedding-3-large"


@pytest.mark.asyncio
async def test_patch_llm_settings_explicit_null_resets_to_default():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.patch("/settings/llm", json={"llm_model": "deepseek/deepseek-chat", "llm_api_key": "sk-x"})
        reset = await client.patch("/settings/llm", json={"llm_model": None, "llm_api_key": None})

    assert reset.status_code == 200
    body = reset.json()
    assert body["llm_model"] == settings.llm_model
    assert body["llm_key_configured"] is False
