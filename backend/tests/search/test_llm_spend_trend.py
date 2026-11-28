import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.analyzer.budget import current_utc_month_start
from app.models import AnalysisCache
from app.search.llm_spend_trend import get_llm_spend_trend


def _cache_row(cost: Decimal, kind: str, created_at: datetime | None = None) -> AnalysisCache:
    kwargs = {
        "content_hash": f"test-llm-spend-trend-{uuid.uuid4()}",
        "model": "test-model",
        "prompt_version": "v1",
        "kind": kind,
        "response": {},
        "tokens_in": 10,
        "tokens_out": 10,
        "cost_usd": cost,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at
    return AnalysisCache(**kwargs)


async def _today_bucket(session, kind: str) -> Decimal:
    today = datetime.now(UTC).date()
    points = await get_llm_spend_trend(session)
    matching = [p for p in points if p.day == today and p.kind == kind]
    return matching[0].cost_usd if matching else Decimal(0)


@pytest.mark.asyncio
async def test_two_rows_same_day_and_kind_sum_together(db_session):
    baseline = await _today_bucket(db_session, "chat")

    db_session.add(_cache_row(Decimal("1.25"), "chat"))
    db_session.add(_cache_row(Decimal("0.75"), "chat"))
    await db_session.commit()

    assert await _today_bucket(db_session, "chat") == baseline + Decimal("2.00")


@pytest.mark.asyncio
async def test_different_kinds_same_day_stay_in_separate_buckets(db_session):
    baseline_chat = await _today_bucket(db_session, "chat")
    baseline_rerank = await _today_bucket(db_session, "rerank")

    db_session.add(_cache_row(Decimal("3.00"), "chat"))
    db_session.add(_cache_row(Decimal("5.00"), "rerank"))
    await db_session.commit()

    assert await _today_bucket(db_session, "chat") == baseline_chat + Decimal("3.00")
    assert await _today_bucket(db_session, "rerank") == baseline_rerank + Decimal("5.00")


@pytest.mark.asyncio
async def test_a_row_from_last_month_is_excluded(db_session):
    baseline = await _today_bucket(db_session, "embedding")
    last_month = current_utc_month_start() - timedelta(days=1)

    db_session.add(_cache_row(Decimal("999.00"), "embedding", created_at=last_month))
    await db_session.commit()

    assert await _today_bucket(db_session, "embedding") == baseline
