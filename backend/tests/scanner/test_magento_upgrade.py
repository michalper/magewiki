import pytest
from sqlalchemy import delete

from app.models import PackagistCache
from app.scanner.magento_upgrade import check_magento_upgrade_readiness

# magento_upgrade's dependencies (resolve_latest_release / fetch_release_*)
# sit behind the shared, test-session-persistent packagist_cache table (see
# conftest.py's db_session — no per-test transaction rollback). Mocking only
# httpx.AsyncClient risks a cache hit from a real call made elsewhere (e.g.
# test_scanner_integration.py's full orchestrator run, which exercises this
# check unmocked, same as every other Phase 10/12 external-call check)
# silently shadowing the mock. Patch at the function boundary instead.


def _patch(monkeypatch, *, tag: str, php_constraint: str | None, component_versions: dict[str, str]):
    async def _resolve_latest_release(session):
        return tag

    async def _fetch_release_php_constraint(session, tag_arg):
        return php_constraint

    async def _fetch_release_component_versions(session, tag_arg):
        return component_versions

    monkeypatch.setattr("app.scanner.magento_upgrade.resolve_latest_release", _resolve_latest_release)
    monkeypatch.setattr(
        "app.scanner.magento_upgrade.fetch_release_php_constraint", _fetch_release_php_constraint
    )
    monkeypatch.setattr(
        "app.scanner.magento_upgrade.fetch_release_component_versions", _fetch_release_component_versions
    )


@pytest.mark.asyncio
async def test_flags_php_incompatibility(db_session, monkeypatch):
    _patch(
        monkeypatch,
        tag="2.4.7",
        php_constraint="~8.1.0||~8.2.0||~8.3.0",
        component_versions={},
    )

    findings = await check_magento_upgrade_readiness(db_session, "^7.4", {})

    assert len(findings) == 1
    assert findings[0].check_type == "magento_php_incompatible"
    assert findings[0].severity == "blocking"
    assert "2.4.7" in findings[0].message


@pytest.mark.asyncio
async def test_flags_a_magento_package_version_blocker(db_session, monkeypatch):
    _patch(
        monkeypatch,
        tag="2.4.7",
        php_constraint="~8.1.0",
        component_versions={"magento/module-sales": "103.0.5"},
    )

    findings = await check_magento_upgrade_readiness(
        db_session, "~8.1.0", {"magento/module-sales": "^100.0"}
    )

    assert len(findings) == 1
    assert findings[0].check_type == "magento_version_blocker"
    assert findings[0].severity == "blocking"
    assert "magento/module-sales" in findings[0].message
    assert "103.0.5" in findings[0].message


@pytest.mark.asyncio
async def test_compatible_module_has_no_findings(db_session, monkeypatch):
    _patch(
        monkeypatch,
        tag="2.4.7",
        php_constraint="~8.1.0",
        component_versions={"magento/module-sales": "103.0.5"},
    )

    findings = await check_magento_upgrade_readiness(
        db_session, "~8.1.0", {"magento/module-sales": "^103.0"}
    )

    assert findings == []


@pytest.mark.asyncio
async def test_fails_open_when_the_release_cannot_be_resolved(db_session, monkeypatch):
    async def _resolve_latest_release(session):
        return None

    monkeypatch.setattr("app.scanner.magento_upgrade.resolve_latest_release", _resolve_latest_release)

    findings = await check_magento_upgrade_readiness(db_session, "^7.4", {"magento/module-sales": "^1.0"})

    assert findings == []


@pytest.mark.asyncio
async def test_magento_github_fails_open_on_http_error(db_session, monkeypatch):
    """resolve_latest_release itself (app/scanner/magento_github.py), one
    layer below check_magento_upgrade_readiness — never raises on a flaky
    GitHub call. Clears its cache row first: packagist_cache is a real,
    test-session-persistent table (no per-test rollback), and this is the
    one test here that exercises the cache miss path directly rather than
    through a mock, so a stale cached value from an earlier real call would
    silently shadow it.
    """
    import httpx

    from app.scanner.magento_github import resolve_latest_release

    await db_session.execute(delete(PackagistCache).where(PackagistCache.cache_key == "magento-github:latest-release"))

    class _RaisingClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *a, **k):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr("app.scanner.magento_github.httpx.AsyncClient", _RaisingClient)

    assert await resolve_latest_release(db_session) is None
