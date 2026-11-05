from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AnalysisCache


def _current_utc_month_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def is_budget_exceeded(session: AsyncSession) -> bool:
    month_start = _current_utc_month_start()
    spent = await session.scalar(
        select(func.coalesce(func.sum(AnalysisCache.cost_usd), 0)).where(
            AnalysisCache.created_at >= month_start
        )
    )
    return Decimal(spent) >= Decimal(str(settings.llm_monthly_budget_usd))
