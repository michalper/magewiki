import httpx
import pytest
from sqlalchemy import delete

from app.models import PackagistCache
from app.scanner.magento_github import (
    fetch_release_component_versions,
    fetch_release_php_constraint,
    resolve_latest_release,
)


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json


class _FakeAsyncClient:
    def __init__(self, responses: dict[str, dict | int], *args, **kwargs):
        # Maps a URL substring to either a JSON body (200) or an int status code.
        self._responses = responses
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, *a, **k):
        self.calls.append(url)
        for key, value in self._responses.items():
            if key in url:
                if isinstance(value, int):
                    return _FakeResponse({}, status_code=value)
                return _FakeResponse(value)
        raise AssertionError(f"unexpected URL: {url}")


async def _clear_cache(session, *cache_keys: str) -> None:
    for key in cache_keys:
        await session.execute(delete(PackagistCache).where(PackagistCache.cache_key == key))
    await session.commit()


@pytest.mark.asyncio
async def test_resolve_latest_release_returns_none_without_a_tag_name(db_session, monkeypatch):
    await _clear_cache(db_session, "magento-github:latest-release")
    monkeypatch.setattr(
        "app.scanner.magento_github.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient({"releases/latest": {}})
    )

    assert await resolve_latest_release(db_session) is None


@pytest.mark.asyncio
async def test_resolve_latest_release_caches_the_tag(db_session, monkeypatch):
    await _clear_cache(db_session, "magento-github:latest-release")
    client = _FakeAsyncClient({"releases/latest": {"tag_name": "2.4.8"}})
    monkeypatch.setattr("app.scanner.magento_github.httpx.AsyncClient", lambda *a, **k: client)

    first = await resolve_latest_release(db_session)
    second = await resolve_latest_release(db_session)

    assert first == second == "2.4.8"
    assert len(client.calls) == 1  # second call served from cache


@pytest.mark.asyncio
async def test_fetch_release_php_constraint_returns_none_on_a_404(db_session, monkeypatch):
    await _clear_cache(db_session, "magento-github:2.4.8:composer.json")
    monkeypatch.setattr(
        "app.scanner.magento_github.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient({"composer.json": 404})
    )

    assert await fetch_release_php_constraint(db_session, "2.4.8") is None


@pytest.mark.asyncio
async def test_fetch_release_php_constraint_returns_none_when_require_is_missing(db_session, monkeypatch):
    await _clear_cache(db_session, "magento-github:2.4.8:composer.json")
    monkeypatch.setattr(
        "app.scanner.magento_github.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient({"composer.json": {"name": "magento/magento2"}}),
    )

    assert await fetch_release_php_constraint(db_session, "2.4.8") is None


@pytest.mark.asyncio
async def test_fetch_release_php_constraint_returns_the_real_constraint(db_session, monkeypatch):
    await _clear_cache(db_session, "magento-github:2.4.8:composer.json")
    monkeypatch.setattr(
        "app.scanner.magento_github.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient({"composer.json": {"require": {"php": "~8.1.0||~8.2.0"}}}),
    )

    assert await fetch_release_php_constraint(db_session, "2.4.8") == "~8.1.0||~8.2.0"


@pytest.mark.asyncio
async def test_fetch_release_php_constraint_uses_the_cache_on_a_second_call(db_session, monkeypatch):
    await _clear_cache(db_session, "magento-github:2.4.8:composer.json")
    client = _FakeAsyncClient({"composer.json": {"require": {"php": "~8.2.0"}}})
    monkeypatch.setattr("app.scanner.magento_github.httpx.AsyncClient", lambda *a, **k: client)

    first = await fetch_release_php_constraint(db_session, "2.4.8")
    second = await fetch_release_php_constraint(db_session, "2.4.8")

    assert first == second == "~8.2.0"
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_fetch_release_component_versions_returns_empty_on_a_404(db_session, monkeypatch):
    await _clear_cache(db_session, "magento-github:2.4.8:composer.json")
    monkeypatch.setattr(
        "app.scanner.magento_github.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient({"composer.json": 404})
    )

    assert await fetch_release_component_versions(db_session, "2.4.8") == {}


@pytest.mark.asyncio
async def test_fetch_release_component_versions_returns_empty_when_replace_is_missing(db_session, monkeypatch):
    await _clear_cache(db_session, "magento-github:2.4.8:composer.json")
    monkeypatch.setattr(
        "app.scanner.magento_github.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient({"composer.json": {"name": "magento/magento2"}}),
    )

    assert await fetch_release_component_versions(db_session, "2.4.8") == {}


@pytest.mark.asyncio
async def test_fetch_release_component_versions_filters_to_magento_packages(db_session, monkeypatch):
    await _clear_cache(db_session, "magento-github:2.4.8:composer.json")
    monkeypatch.setattr(
        "app.scanner.magento_github.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(
            {
                "composer.json": {
                    "replace": {
                        "magento/framework": "103.0.0",
                        "symfony/console": "6.4.0",
                    }
                }
            }
        ),
    )

    assert await fetch_release_component_versions(db_session, "2.4.8") == {"magento/framework": "103.0.0"}


@pytest.mark.asyncio
async def test_fetch_raw_json_returns_none_on_an_http_error(db_session, monkeypatch):
    await _clear_cache(db_session, "magento-github:2.4.8:composer.json")

    class _RaisingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.scanner.magento_github.httpx.AsyncClient", lambda *a, **k: _RaisingClient())

    assert await fetch_release_php_constraint(db_session, "2.4.8") is None
