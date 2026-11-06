from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.analyzer.client import LlmCallResult
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


@pytest.fixture(autouse=True)
def _stub_embedding_probe(monkeypatch):
    """PATCH /settings/llm probes the real embedding dimension via embed_text()
    whenever embedding_model changes — stub it to a vector matching the
    deployment's configured dimension by default (no real API calls in tests);
    individual tests override this to exercise the mismatch-rejection path.
    """

    async def fake_embed_text(text, *, model, api_key, api_base=None):
        vector = [0.0] * settings.embedding_dimensions
        return vector, LlmCallResult(response_json={}, tokens_in=1, tokens_out=0, cost_usd=Decimal(0))

    monkeypatch.setattr("app.api.routes.llm_settings.embed_text", fake_embed_text)


@pytest.mark.asyncio
async def test_get_llm_settings_defaults_when_unconfigured():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/settings/llm")

    assert response.status_code == 200
    body = response.json()
    assert body["llm_model"] == settings.llm_model
    assert body["llm_key_configured"] is False
    assert body["llm_api_base"] is None
    assert body["embedding_model"] == settings.embedding_model
    assert body["embedding_key_configured"] is False
    assert body["embedding_api_base"] is None


@pytest.mark.asyncio
async def test_patch_llm_settings_sets_and_resets_api_base():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        set_response = await client.patch(
            "/settings/llm",
            json={"llm_model": "ollama_chat/llama3.1", "llm_api_base": "http://host.docker.internal:11434"},
        )
        reset_response = await client.patch("/settings/llm", json={"llm_model": None, "llm_api_base": None})

    assert set_response.json()["llm_api_base"] == "http://host.docker.internal:11434"
    assert reset_response.json()["llm_api_base"] is None


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


@pytest.mark.asyncio
async def test_patch_embedding_model_with_matching_dimension_succeeds(monkeypatch):
    async def fake_embed_text(text, *, model, api_key, api_base=None):
        return [0.0] * settings.embedding_dimensions, LlmCallResult(
            response_json={}, tokens_in=1, tokens_out=0, cost_usd=Decimal(0)
        )

    monkeypatch.setattr("app.api.routes.llm_settings.embed_text", fake_embed_text)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/settings/llm", json={"embedding_model": "openai/text-embedding-3-small"})

    assert response.status_code == 200
    assert response.json()["embedding_model"] == "openai/text-embedding-3-small"


@pytest.mark.asyncio
async def test_patch_embedding_model_with_mismatched_dimension_is_rejected(monkeypatch):
    """Real-world bug this guards against: chunks.embedding is a fixed-dimension
    pgvector column — selecting a model with a different output dimension (e.g.
    bge-m3's 1024 vs. the default 1536) used to only fail later, inside an
    unrelated scan's embed step, with no guard here at all.
    """

    async def fake_embed_text(text, *, model, api_key, api_base=None):
        return [0.0] * 1024, LlmCallResult(response_json={}, tokens_in=1, tokens_out=0, cost_usd=Decimal(0))

    monkeypatch.setattr("app.api.routes.llm_settings.embed_text", fake_embed_text)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/settings/llm", json={"embedding_model": "ollama/bge-m3"})
        unchanged = await client.get("/settings/llm")

    assert response.status_code == 400
    assert "1024" in response.text
    assert str(settings.embedding_dimensions) in response.text
    assert unchanged.json()["embedding_model"] == settings.embedding_model  # rejected, not persisted


@pytest.mark.asyncio
async def test_patch_embedding_model_surfaces_a_probe_failure_as_400(monkeypatch):
    async def fake_embed_text(text, *, model, api_key, api_base=None):
        raise RuntimeError("no credits remaining")

    monkeypatch.setattr("app.api.routes.llm_settings.embed_text", fake_embed_text)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/settings/llm", json={"embedding_model": "openai/text-embedding-3-small"})

    assert response.status_code == 400
    assert "no credits remaining" in response.text


@pytest.mark.asyncio
async def test_patch_rejects_changing_llm_api_base_alone_when_a_key_is_already_configured():
    """Security fix: every LLM call sends the stored api_key to whatever api_base is
    configured — allowing api_base to change without re-proving the key lets an
    unauthenticated caller redirect an already-provisioned secret's destination
    without ever needing to know its value.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.patch("/settings/llm", json={"llm_api_key": "sk-real-secret"})
        attack = await client.patch("/settings/llm", json={"llm_api_base": "https://attacker.example"})
        unchanged = await client.get("/settings/llm")

    assert attack.status_code == 400
    assert "llm_api_key" in attack.json()["detail"]
    assert unchanged.json()["llm_api_base"] is None  # rejected, not persisted


@pytest.mark.asyncio
async def test_patch_allows_changing_llm_api_base_together_with_the_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.patch("/settings/llm", json={"llm_api_key": "sk-real-secret"})
        response = await client.patch(
            "/settings/llm", json={"llm_api_key": "sk-new-secret", "llm_api_base": "https://my-proxy.example"}
        )

    assert response.status_code == 200
    assert response.json()["llm_api_base"] == "https://my-proxy.example"


@pytest.mark.asyncio
async def test_patch_allows_changing_llm_api_base_alone_when_no_key_is_configured_yet():
    """Nothing to protect yet — the coupling check only applies once a real secret
    is actually stored.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch("/settings/llm", json={"llm_api_base": "http://host.docker.internal:11434"})

    assert response.status_code == 200
    assert response.json()["llm_api_base"] == "http://host.docker.internal:11434"


@pytest.mark.asyncio
async def test_patch_rejects_changing_embedding_api_base_alone_when_a_key_is_already_configured():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.patch("/settings/llm", json={"embedding_api_key": "sk-real-secret"})
        attack = await client.patch(
            "/settings/llm", json={"embedding_api_base": "https://attacker.example"}
        )
        unchanged = await client.get("/settings/llm")

    assert attack.status_code == 400
    assert "embedding_api_key" in attack.json()["detail"]
    assert unchanged.json()["embedding_api_base"] is None
