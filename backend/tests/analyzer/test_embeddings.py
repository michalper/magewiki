from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.analyzer.embeddings import embed_query_text, embed_text, hash_text
from app.observability import LLM_CALL_COST_USD, LLM_CALLS_TOTAL


def _fake_response(vector: list[float], prompt_tokens: int = 10) -> SimpleNamespace:
    return SimpleNamespace(data=[{"embedding": vector}], usage=SimpleNamespace(prompt_tokens=prompt_tokens))


def test_hash_text_is_a_deterministic_sha256_hex_digest():
    assert hash_text("hello") == hash_text("hello")
    assert hash_text("hello") != hash_text("world")
    assert len(hash_text("hello")) == 64


@pytest.mark.asyncio
async def test_embed_text_records_an_embedding_metric_per_real_call(monkeypatch):
    model = "openai/text-embedding-3-small"
    before_calls = LLM_CALLS_TOTAL.labels(model, "embedding")._value.get()
    before_cost_sum = LLM_CALL_COST_USD.labels(model, "embedding")._sum.get()

    async def fake_aembedding(**kwargs):
        return _fake_response([0.1, 0.2])

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", lambda **k: 0.002)

    await embed_text("some text", model=model, api_key="k")

    assert LLM_CALLS_TOTAL.labels(model, "embedding")._value.get() == before_calls + 1
    assert LLM_CALL_COST_USD.labels(model, "embedding")._sum.get() == pytest.approx(before_cost_sum + 0.002)


@pytest.mark.asyncio
async def test_embed_text_uses_litellms_own_cost_when_it_succeeds(monkeypatch):
    async def fake_aembedding(**kwargs):
        return _fake_response([0.1, 0.2])

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", lambda **k: 0.002)

    vector, result = await embed_text("some text", model="openai/text-embedding-3-small", api_key="k")

    assert vector == [0.1, 0.2]
    assert result.tokens_in == 10
    assert result.tokens_out == 0
    assert result.cost_usd == Decimal("0.002")
    assert result.response_json == {"embedding": [0.1, 0.2]}


@pytest.mark.asyncio
async def test_embed_text_falls_back_to_computed_cost_when_litellm_raises(monkeypatch):
    async def fake_aembedding(**kwargs):
        return _fake_response([0.3])

    def raising_cost(**kwargs):
        raise RuntimeError("no pricing data for this model")

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", raising_cost)
    monkeypatch.setattr("app.analyzer.embeddings.compute_cost_usd", lambda model, tin, tout: Decimal("0.0001"))

    _vector, result = await embed_text("some text", model="openai/text-embedding-3-small", api_key="k")

    assert result.cost_usd == Decimal("0.0001")


@pytest.mark.asyncio
async def test_embed_text_falls_back_to_computed_cost_when_litellm_returns_zero(monkeypatch):
    async def fake_aembedding(**kwargs):
        return _fake_response([0.3])

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", lambda **k: 0)
    monkeypatch.setattr("app.analyzer.embeddings.compute_cost_usd", lambda model, tin, tout: Decimal("0.0002"))

    _vector, result = await embed_text("some text", model="m", api_key="k")

    assert result.cost_usd == Decimal("0.0002")


@pytest.mark.asyncio
async def test_embed_query_text_returns_only_the_vector(monkeypatch):
    async def fake_aembedding(**kwargs):
        return _fake_response([0.5, 0.6])

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", lambda **k: 0.001)

    vector = await embed_query_text("a query", model="m", api_key="k", api_base="http://localhost:11434")

    assert vector == [0.5, 0.6]
