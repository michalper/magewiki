import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.analyzer.budget import BudgetExceededError
from app.analyzer.embeddings import embed_query_text, embed_text, embed_texts_batch, hash_text
from app.analyzer.prompts import EMBEDDING_PROMPT_VERSION
from app.config import settings
from app.models import AnalysisCache
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


def _fake_batch_response(vectors: list[list[float]], prompt_tokens: int, indices: list[int] | None = None):
    data = [{"embedding": v, "index": i} for v, i in zip(vectors, indices or range(len(vectors)), strict=True)]
    return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=prompt_tokens))


@pytest.mark.asyncio
async def test_embed_texts_batch_returns_an_empty_list_without_making_a_call(monkeypatch):
    async def fake_aembedding(**kwargs):
        pytest.fail("must not call the embeddings API for an empty batch")

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)

    assert await embed_texts_batch([], model="m", api_key="k") == []


@pytest.mark.asyncio
async def test_embed_texts_batch_makes_exactly_one_call_for_several_texts(monkeypatch):
    calls = []

    async def fake_aembedding(**kwargs):
        calls.append(kwargs)
        return _fake_batch_response([[0.1], [0.2], [0.3]], prompt_tokens=30)

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", lambda **k: 0.003)

    results = await embed_texts_batch(["aa", "bb", "cc"], model="m", api_key="k")

    assert len(calls) == 1
    assert calls[0]["input"] == ["aa", "bb", "cc"]
    assert [v for v, _r in results] == [[0.1], [0.2], [0.3]]


@pytest.mark.asyncio
async def test_embed_texts_batch_splits_tokens_and_cost_so_they_sum_to_the_real_total(monkeypatch):
    """The embeddings API bills (and reports usage for) the whole batch as one
    call, with no per-item breakdown. Each returned LlmCallResult gets its own
    plausible share, but critically the SUM across the batch must equal the
    one real, billed total exactly -- the monthly budget is a sum over every
    AnalysisCache.cost_usd row, so under- or over-allocating by rounding would
    silently corrupt that ledger.
    """

    async def fake_aembedding(**kwargs):
        return _fake_batch_response([[0.1], [0.2], [0.3]], prompt_tokens=100)

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", lambda **k: 0.0033333)

    # Deliberately uneven lengths so an equal-split-by-count would visibly
    # differ from the real, length-proportional allocation this asserts.
    texts = ["a", "bb", "ccccccc"]
    results = await embed_texts_batch(texts, model="m", api_key="k")

    assert sum(r.tokens_in for _v, r in results) == 100
    assert sum(r.cost_usd for _v, r in results) == Decimal("0.0033333")
    # The longest text gets the largest share of both.
    assert results[2][1].tokens_in > results[1][1].tokens_in > results[0][1].tokens_in


@pytest.mark.asyncio
async def test_embed_texts_batch_falls_back_to_computed_cost_when_litellm_raises(monkeypatch):
    async def fake_aembedding(**kwargs):
        return _fake_batch_response([[0.1], [0.2]], prompt_tokens=20)

    def raising_cost(**kwargs):
        raise RuntimeError("no pricing data for this model")

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", raising_cost)
    monkeypatch.setattr("app.analyzer.embeddings.compute_cost_usd", lambda model, tin, tout: Decimal("0.0001"))

    results = await embed_texts_batch(["aa", "bb"], model="m", api_key="k")

    assert sum(r.cost_usd for _v, r in results) == Decimal("0.0001")


@pytest.mark.asyncio
async def test_embed_texts_batch_falls_back_to_computed_cost_when_litellm_returns_zero(monkeypatch):
    async def fake_aembedding(**kwargs):
        return _fake_batch_response([[0.1], [0.2]], prompt_tokens=20)

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", lambda **k: 0)
    monkeypatch.setattr("app.analyzer.embeddings.compute_cost_usd", lambda model, tin, tout: Decimal("0.0002"))

    results = await embed_texts_batch(["aa", "bb"], model="m", api_key="k")

    assert sum(r.cost_usd for _v, r in results) == Decimal("0.0002")


@pytest.mark.asyncio
async def test_embed_texts_batch_reorders_by_the_responses_own_index_field(monkeypatch):
    """OpenAI documents returning batch embeddings in input order already, but
    each item also carries its own "index" -- sorting by it (rather than
    trusting response.data's own position) is what actually guarantees the
    returned vectors line up with the input texts if that ordering guarantee
    is ever wrong for some provider litellm proxies to."""

    async def fake_aembedding(**kwargs):
        # Response data deliberately out of order: index 2 first, then 0, then 1.
        return _fake_batch_response([[2.0], [0.0], [1.0]], prompt_tokens=30, indices=[2, 0, 1])

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", lambda **k: 0.003)

    results = await embed_texts_batch(["first", "second", "third"], model="m", api_key="k")

    assert [v for v, _r in results] == [[0.0], [1.0], [2.0]]


@pytest.mark.asyncio
async def test_embed_query_text_with_a_session_records_cost_to_analysis_cache(db_session, monkeypatch):
    """Closes the gap the review found: every live caller of embed_query_text now
    passes its session, so a real query-embedding call is no longer invisible to
    the monthly budget ledger (AnalysisCache is the only table is_budget_exceeded
    reads)."""
    model = f"openai/text-embedding-3-small-{uuid.uuid4().hex[:8]}"  # unique per test, avoids cross-test cache hits
    query = f"query text {uuid.uuid4().hex[:8]}"

    async def fake_aembedding(**kwargs):
        return _fake_response([0.7, 0.8])

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", lambda **k: 0.001)

    vector = await embed_query_text(query, model=model, api_key="k", session=db_session)

    assert vector == [0.7, 0.8]
    row = await db_session.scalar(
        select(AnalysisCache).where(
            AnalysisCache.content_hash == hash_text(query),
            AnalysisCache.model == model,
            AnalysisCache.prompt_version == EMBEDDING_PROMPT_VERSION,
            AnalysisCache.kind == "embedding",
        )
    )
    assert row is not None
    assert row.cost_usd == Decimal("0.001")


@pytest.mark.asyncio
async def test_embed_query_text_with_a_session_reuses_a_cached_embedding_at_no_extra_cost(db_session, monkeypatch):
    model = f"openai/text-embedding-3-small-{uuid.uuid4().hex[:8]}"
    query = f"repeated query {uuid.uuid4().hex[:8]}"
    call_count = 0

    async def fake_aembedding(**kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_response([0.1, 0.1])

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)
    monkeypatch.setattr("app.analyzer.embeddings.litellm.completion_cost", lambda **k: 0.001)

    first = await embed_query_text(query, model=model, api_key="k", session=db_session)
    second = await embed_query_text(query, model=model, api_key="k", session=db_session)

    assert first == second == [0.1, 0.1]
    assert call_count == 1  # second call was a cache hit, no new embedding call


@pytest.mark.asyncio
async def test_embed_query_text_with_a_session_raises_once_budget_is_exceeded(db_session, monkeypatch):
    model = f"openai/text-embedding-3-small-{uuid.uuid4().hex[:8]}"
    query = f"over budget query {uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "llm_monthly_budget_usd", -1.0)  # already exceeded, unconditionally

    async def fake_aembedding(**kwargs):
        pytest.fail("embed_text must not be called once the budget is already exceeded")

    monkeypatch.setattr("app.analyzer.embeddings.litellm.aembedding", fake_aembedding)

    with pytest.raises(BudgetExceededError):
        await embed_query_text(query, model=model, api_key="k", session=db_session)
