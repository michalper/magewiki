from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.budget import current_utc_month_start
from app.models import AnalysisCache


@dataclass
class LlmSpendPoint:
    day: date
    kind: str
    cost_usd: Decimal


async def get_llm_spend_trend(session: AsyncSession) -> list[LlmSpendPoint]:
    """Daily spend by `AnalysisCache.kind`, scoped to the current UTC month --
    the same month boundary `get_monthly_spend_usd`/`is_budget_exceeded` use,
    since this is explicitly a *this month's burn-down* view, not an
    unbounded history (`analysis_cache` is never pruned, so an unscoped query
    would only get more expensive over time for no benefit this feature
    needs).
    """
    month_start = current_utc_month_start()
    day_column = cast(AnalysisCache.created_at, Date)
    rows = (
        await session.execute(
            select(day_column.label("day"), AnalysisCache.kind, func.sum(AnalysisCache.cost_usd))
            .where(AnalysisCache.created_at >= month_start)
            .group_by(day_column, AnalysisCache.kind)
            .order_by(day_column)
        )
    ).all()
    return [LlmSpendPoint(day=day, kind=kind, cost_usd=Decimal(cost_usd)) for day, kind, cost_usd in rows]
