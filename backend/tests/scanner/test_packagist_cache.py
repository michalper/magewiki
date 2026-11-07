import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models import PackagistCache
from app.scanner.packagist_cache import get_cached, set_cached


@pytest.mark.asyncio
async def test_get_cached_returns_none_for_an_unknown_key(db_session):
    assert await get_cached(db_session, f"unknown-{uuid.uuid4().hex[:8]}") is None


@pytest.mark.asyncio
async def test_set_then_get_cached_round_trips(db_session):
    key = f"p2:vendor/pkg-{uuid.uuid4().hex[:8]}"
    await set_cached(db_session, key, {"packages": {"vendor/pkg": []}})

    assert await get_cached(db_session, key) == {"packages": {"vendor/pkg": []}}


@pytest.mark.asyncio
async def test_get_cached_returns_none_once_the_ttl_has_expired(db_session):
    key = f"p2:vendor/pkg-{uuid.uuid4().hex[:8]}"
    db_session.add(
        PackagistCache(
            cache_key=key, response_json={"stale": True}, fetched_at=datetime.now(UTC) - timedelta(hours=25)
        )
    )
    await db_session.commit()

    assert await get_cached(db_session, key) is None
