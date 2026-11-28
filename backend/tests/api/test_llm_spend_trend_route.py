import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app
from app.models import AnalysisCache


async def _add_cache_row(session, cost: Decimal, kind: str) -> None:
    session.add(
        AnalysisCache(
            content_hash=f"test-llm-spend-trend-route-{uuid.uuid4()}",
            model="test-model",
            prompt_version="v1",
            kind=kind,
            response={},
            tokens_in=10,
            tokens_out=10,
            cost_usd=cost,
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_spend_trend_route_includes_the_budget_and_a_real_point(db_session):
    await _add_cache_row(db_session, Decimal("4.00"), "chat")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/settings/llm/spend-trend")

    assert response.status_code == 200
    body = response.json()
    assert body["monthly_budget_usd"] == settings.llm_monthly_budget_usd
    assert Decimal(body["total_spent_usd"]) >= Decimal("4.00")

    today = datetime.now(UTC).date().isoformat()
    matching = [p for p in body["points"] if p["day"] == today and p["kind"] == "chat"]
    assert len(matching) == 1
    assert Decimal(matching[0]["cost_usd"]) >= Decimal("4.00")
