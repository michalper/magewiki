import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.analyzer.budget import is_budget_exceeded
from app.config import settings
from app.models import AnalysisCache


def _month_start(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _current_month_spend(session) -> Decimal:
    month_start = _month_start(datetime.now(UTC))
    spent = await session.scalar(
        select(func.coalesce(func.sum(AnalysisCache.cost_usd), 0)).where(AnalysisCache.created_at >= month_start)
    )
    return Decimal(spent)


def _cache_row(cost: Decimal, created_at: datetime | None = None) -> AnalysisCache:
    kwargs = {
        "content_hash": f"test-budget-{uuid.uuid4()}",
        "model": "test-model",
        "prompt_version": "v1",
        "kind": "file_summary",
        "response": {},
        "tokens_in": 10,
        "tokens_out": 10,
        "cost_usd": cost,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at
    return AnalysisCache(**kwargs)


@pytest.mark.asyncio
async def test_budget_not_exceeded_below_threshold(db_session, monkeypatch):
    baseline = await _current_month_spend(db_session)
    monkeypatch.setattr(settings, "llm_monthly_budget_usd", float(baseline) + 10.0)

    assert await is_budget_exceeded(db_session) is False


@pytest.mark.asyncio
async def test_budget_exceeded_after_crossing_threshold(db_session, monkeypatch):
    baseline = await _current_month_spend(db_session)
    monkeypatch.setattr(settings, "llm_monthly_budget_usd", float(baseline) + 0.01)

    db_session.add(_cache_row(Decimal("1.00")))
    await db_session.commit()

    assert await is_budget_exceeded(db_session) is True


@pytest.mark.asyncio
async def test_budget_excludes_previous_month_spend(db_session, monkeypatch):
    baseline = await _current_month_spend(db_session)
    monkeypatch.setattr(settings, "llm_monthly_budget_usd", float(baseline) + 10.0)

    last_month = _month_start(datetime.now(UTC)) - timedelta(days=1)
    db_session.add(_cache_row(Decimal("999.00"), created_at=last_month))
    await db_session.commit()

    assert await is_budget_exceeded(db_session) is False
