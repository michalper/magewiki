import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.analyzer.prompts import QUERY_REWRITE_PROMPT_VERSION
from app.config import settings
from app.models import AnalysisCache
from app.observability import LLM_CALL_COST_USD, LLM_CALLS_TOTAL
from app.search.query_rewrite import rewrite_query


def _tool_response(rewritten: str) -> SimpleNamespace:
    tool_call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps({"rewritten_query": rewritten})))
    message = SimpleNamespace(tool_calls=[tool_call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=50, completion_tokens=10),
    )


@pytest.mark.asyncio
async def test_rewrite_query_returns_the_models_rewrite(db_session, monkeypatch):
    async def fake_acompletion(**kwargs):
        return _tool_response("Klaviyo email marketing integration")

    monkeypatch.setattr("app.search.query_rewrite.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.search.query_rewrite.litellm.completion_cost", lambda **k: 0.0003)

    result = await rewrite_query(db_session, "klavyo thing")

    assert result == "Klaviyo email marketing integration"


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_for_a_blank_query(db_session):
    assert await rewrite_query(db_session, "   ") == "   "


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_when_over_budget(db_session, monkeypatch):
    monkeypatch.setattr(settings, "llm_monthly_budget_usd", -1.0)  # already exceeded, unconditionally

    called = False

    async def fake_acompletion(**kwargs):
        nonlocal called
        called = True
        return _tool_response("rewritten")

    monkeypatch.setattr("app.search.query_rewrite.litellm.acompletion", fake_acompletion)

    result = await rewrite_query(db_session, "original query")

    assert called is False
    assert result == "original query"


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_on_a_provider_error(db_session, monkeypatch):
    async def fake_acompletion(**kwargs):
        raise RuntimeError("provider rejected the request")

    monkeypatch.setattr("app.search.query_rewrite.litellm.acompletion", fake_acompletion)

    result = await rewrite_query(db_session, "original query")

    assert result == "original query"


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_when_no_tool_call_is_returned(db_session, monkeypatch):
    async def fake_acompletion(**kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )

    monkeypatch.setattr("app.search.query_rewrite.litellm.acompletion", fake_acompletion)

    result = await rewrite_query(db_session, "original query")

    assert result == "original query"


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_when_the_model_returns_an_empty_rewrite(db_session, monkeypatch):
    async def fake_acompletion(**kwargs):
        return _tool_response("   ")

    monkeypatch.setattr("app.search.query_rewrite.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.search.query_rewrite.litellm.completion_cost", lambda **k: 0.0003)

    result = await rewrite_query(db_session, "original query")

    assert result == "original query"


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_to_computed_cost_when_litellm_cost_fails(db_session, monkeypatch):
    async def fake_acompletion(**kwargs):
        return _tool_response("rewritten")

    def _raising_cost(**kwargs):
        raise RuntimeError("no pricing data for this model")

    monkeypatch.setattr("app.search.query_rewrite.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.search.query_rewrite.litellm.completion_cost", _raising_cost)
    monkeypatch.setattr("app.search.query_rewrite.compute_cost_usd", lambda model, tin, tout: Decimal("0.0004"))

    await rewrite_query(db_session, "original query")

    row = (
        await db_session.execute(
            AnalysisCache.__table__.select()
            .where(AnalysisCache.kind == "query_rewrite")
            .order_by(AnalysisCache.id.desc())
            .limit(1)
        )
    ).first()
    assert row.cost_usd == Decimal("0.0004")


@pytest.mark.asyncio
async def test_rewrite_query_persists_cost_and_records_metrics(db_session, monkeypatch):
    model = "anthropic/claude-haiku-5-5"
    before_calls = LLM_CALLS_TOTAL.labels(model, "query_rewrite")._value.get()
    before_cost_sum = LLM_CALL_COST_USD.labels(model, "query_rewrite")._sum.get()

    async def fake_acompletion(**kwargs):
        assert kwargs["model"] == model
        return _tool_response("rewritten query")

    monkeypatch.setattr("app.search.query_rewrite.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.search.query_rewrite.litellm.completion_cost", lambda **k: 0.0002)

    await rewrite_query(db_session, "original query")

    assert LLM_CALLS_TOTAL.labels(model, "query_rewrite")._value.get() == before_calls + 1
    assert LLM_CALL_COST_USD.labels(model, "query_rewrite")._sum.get() == pytest.approx(before_cost_sum + 0.0002)

    row = (
        await db_session.execute(
            AnalysisCache.__table__.select()
            .where(AnalysisCache.kind == "query_rewrite")
            .order_by(AnalysisCache.id.desc())
            .limit(1)
        )
    ).first()
    assert row is not None
    assert row.cost_usd == Decimal("0.0002")
    assert row.prompt_version == QUERY_REWRITE_PROMPT_VERSION
    assert row.model == model
