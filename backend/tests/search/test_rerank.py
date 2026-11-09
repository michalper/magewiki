import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.analyzer.prompts import RERANK_PROMPT_VERSION
from app.config import settings
from app.models import AnalysisCache
from app.observability import LLM_CALL_COST_USD, LLM_CALLS_TOTAL
from app.search.hybrid import SearchResult
from app.search.rerank import rerank_results


def _result(chunk_id: int, text: str = "some chunk text") -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id, chunk_type="file", module_id=1, module_name="Vendor_Module",
        relative_path="Foo.php", text=text, score=0.5,
    )


def _tool_response(ranked_ids: list[int]) -> SimpleNamespace:
    tool_call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps({"ranked_chunk_ids": ranked_ids})))
    message = SimpleNamespace(tool_calls=[tool_call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
    )


@pytest.mark.asyncio
async def test_rerank_results_returns_the_models_order(db_session, monkeypatch):
    results = [_result(1), _result(2), _result(3)]

    async def fake_acompletion(**kwargs):
        return _tool_response([3, 1, 2])

    monkeypatch.setattr("app.search.rerank.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.search.rerank.litellm.completion_cost", lambda **k: 0.0015)

    reordered = await rerank_results(db_session, "some query", results, top_k=3)

    assert [r.chunk_id for r in reordered] == [3, 1, 2]


@pytest.mark.asyncio
async def test_rerank_results_respects_top_k(db_session, monkeypatch):
    results = [_result(1), _result(2), _result(3)]

    async def fake_acompletion(**kwargs):
        return _tool_response([3, 1, 2])

    monkeypatch.setattr("app.search.rerank.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.search.rerank.litellm.completion_cost", lambda **k: 0.0015)

    reordered = await rerank_results(db_session, "some query", results, top_k=2)

    assert [r.chunk_id for r in reordered] == [3, 1]


@pytest.mark.asyncio
async def test_rerank_results_drops_hallucinated_ids_and_appends_omitted_ones_in_order(db_session, monkeypatch):
    """The model named an id (999) that was never a real candidate, and never
    mentioned chunk 2 at all -- the hallucinated id must not leak into the
    result, and the omitted real candidate must still come back rather than
    silently vanishing.
    """
    results = [_result(1), _result(2), _result(3)]

    async def fake_acompletion(**kwargs):
        return _tool_response([3, 999, 1])

    monkeypatch.setattr("app.search.rerank.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.search.rerank.litellm.completion_cost", lambda **k: 0.0015)

    reordered = await rerank_results(db_session, "some query", results, top_k=10)

    assert [r.chunk_id for r in reordered] == [3, 1, 2]


@pytest.mark.asyncio
async def test_rerank_results_falls_back_when_over_budget(db_session, monkeypatch):
    monkeypatch.setattr(settings, "llm_monthly_budget_usd", -1.0)  # already exceeded, unconditionally
    results = [_result(1), _result(2), _result(3)]

    called = False

    async def fake_acompletion(**kwargs):
        nonlocal called
        called = True
        return _tool_response([3, 2, 1])

    monkeypatch.setattr("app.search.rerank.litellm.acompletion", fake_acompletion)

    reordered = await rerank_results(db_session, "some query", results, top_k=2)

    assert called is False
    assert [r.chunk_id for r in reordered] == [1, 2]  # original hybrid order, just sliced


@pytest.mark.asyncio
async def test_rerank_results_falls_back_on_a_provider_error(db_session, monkeypatch):
    results = [_result(1), _result(2)]

    async def fake_acompletion(**kwargs):
        raise RuntimeError("provider rejected the request")

    monkeypatch.setattr("app.search.rerank.litellm.acompletion", fake_acompletion)

    reordered = await rerank_results(db_session, "some query", results, top_k=2)

    assert [r.chunk_id for r in reordered] == [1, 2]


@pytest.mark.asyncio
async def test_rerank_results_falls_back_when_no_tool_call_is_returned(db_session, monkeypatch):
    results = [_result(1), _result(2)]

    async def fake_acompletion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )

    monkeypatch.setattr("app.search.rerank.litellm.acompletion", fake_acompletion)

    reordered = await rerank_results(db_session, "some query", results, top_k=2)

    assert [r.chunk_id for r in reordered] == [1, 2]


@pytest.mark.asyncio
async def test_rerank_results_falls_back_to_computed_cost_when_litellm_cost_fails(db_session, monkeypatch):
    results = [_result(1), _result(2)]

    async def fake_acompletion(**kwargs):
        return _tool_response([2, 1])

    def _raising_cost(**kwargs):
        raise RuntimeError("no pricing data for this model")

    monkeypatch.setattr("app.search.rerank.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.search.rerank.litellm.completion_cost", _raising_cost)
    monkeypatch.setattr("app.search.rerank.compute_cost_usd", lambda model, tin, tout: Decimal("0.0009"))

    await rerank_results(db_session, "some query", results, top_k=2)

    row = (
        await db_session.execute(
            AnalysisCache.__table__.select()
            .where(AnalysisCache.kind == "rerank")
            .order_by(AnalysisCache.id.desc())
            .limit(1)
        )
    ).first()
    assert row.cost_usd == Decimal("0.0009")


@pytest.mark.asyncio
async def test_rerank_results_returns_empty_for_no_candidates(db_session):
    assert await rerank_results(db_session, "some query", [], top_k=5) == []


@pytest.mark.asyncio
async def test_rerank_results_persists_cost_and_records_metrics(db_session, monkeypatch):
    model = "anthropic/claude-haiku-5-5"
    before_calls = LLM_CALLS_TOTAL.labels(model, "rerank")._value.get()
    before_cost_sum = LLM_CALL_COST_USD.labels(model, "rerank")._sum.get()

    results = [_result(1), _result(2)]

    async def fake_acompletion(**kwargs):
        assert kwargs["model"] == model
        return _tool_response([2, 1])

    monkeypatch.setattr("app.search.rerank.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.search.rerank.litellm.completion_cost", lambda **k: 0.0012)

    await rerank_results(db_session, "some query", results, top_k=2)

    assert LLM_CALLS_TOTAL.labels(model, "rerank")._value.get() == before_calls + 1
    assert LLM_CALL_COST_USD.labels(model, "rerank")._sum.get() == pytest.approx(before_cost_sum + 0.0012)

    row = (
        await db_session.execute(
            AnalysisCache.__table__.select()
            .where(AnalysisCache.kind == "rerank")
            .order_by(AnalysisCache.id.desc())
            .limit(1)
        )
    ).first()
    assert row is not None
    assert row.cost_usd == Decimal("0.0012")
    assert row.prompt_version == RERANK_PROMPT_VERSION
    assert row.model == model
