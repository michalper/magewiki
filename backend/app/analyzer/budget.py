from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AnalysisCache, Module


def _current_utc_month_start() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def get_monthly_spend_usd(session: AsyncSession) -> Decimal:
    month_start = _current_utc_month_start()
    raw_spent = await session.scalar(
        select(func.coalesce(func.sum(AnalysisCache.cost_usd), 0)).where(
            AnalysisCache.created_at >= month_start
        )
    )
    # coalesce(..., 0) means this is never actually NULL for a real result row, but
    # an aggregate-with-no-matching-rows query still always returns exactly one row
    # in Postgres, so this guard is defensive correctness, not dead code bending to
    # satisfy mypy.
    return Decimal(str(raw_spent)) if raw_spent is not None else Decimal(0)


async def is_budget_exceeded(session: AsyncSession) -> bool:
    spent = await get_monthly_spend_usd(session)
    return spent >= Decimal(str(settings.llm_monthly_budget_usd))


async def pause_module_for_budget(session: AsyncSession, module_id: int, module_current_hash: str) -> None:
    """Shared by every jobs.py call site that aborts on is_budget_exceeded() —
    always the same update+commit, guarded by current_hash like every other
    state transition in jobs.py (a stale job must not pause a module that a
    newer scan generation has already moved past).
    """
    await session.execute(
        update(Module)
        .where(Module.id == module_id, Module.current_hash == module_current_hash)
        .values(state="paused_budget")
    )
    await session.commit()
