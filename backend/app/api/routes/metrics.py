from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.analyzer.budget import get_monthly_spend_usd
from app.db import get_session
from app.observability import LLM_MONTHLY_SPEND_USD, render_metrics

router = APIRouter()


@router.get("/metrics")
async def metrics(session: AsyncSession = Depends(get_session)) -> Response:
    """Prometheus text exposition. llm_monthly_spend_usd is set here, right
    before serializing, rather than kept continuously up to date by a
    background loop -- a gauge only needs to be correct at scrape time, and
    this avoids running an extra polling task for a value nothing else reads.
    """
    spend = await get_monthly_spend_usd(session)
    LLM_MONTHLY_SPEND_USD.set(float(spend))
    return render_metrics()
