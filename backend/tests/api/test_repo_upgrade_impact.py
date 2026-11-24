from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.main import app
from app.models import ComposerPackageRequirement, Module, PackagistCache

REPO_ROOT = "/tmp/upgrade-impact-test-repo"


def _patch_release(monkeypatch, *, php_constraint: str | None, component_versions: dict[str, str]):
    async def _fetch_release_php_constraint(session, tag):
        return php_constraint

    async def _fetch_release_component_versions(session, tag):
        return component_versions

    monkeypatch.setattr(
        "app.api.routes.modules.fetch_release_php_constraint", _fetch_release_php_constraint
    )
    monkeypatch.setattr(
        "app.api.routes.modules.fetch_release_component_versions", _fetch_release_component_versions
    )


async def _make_module(
    db_session, *, name: str, php_constraint: str | None, path: str = "app/code/Vendor/Module"
) -> Module:
    module = Module(
        repo_root=REPO_ROOT,
        name=name,
        path=path,
        source_type="standalone",
        state="up_to_date",
        enabled=True,
        current_hash=f"hash-{name}",
        php_constraint=php_constraint,
        last_scanned_at=datetime.now(UTC),
    )
    db_session.add(module)
    await db_session.flush()
    return module


async def _cleanup(db_session, *modules: Module) -> None:
    await db_session.execute(delete(Module).where(Module.id.in_([m.id for m in modules])))
    await db_session.commit()


async def _get(version: str, repo_root: str = REPO_ROOT):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/repos/upgrade-impact", params={"repo_root": repo_root, "version": version})


@pytest.mark.asyncio
async def test_flags_a_module_incompatible_on_php_constraint(db_session, monkeypatch):
    _patch_release(monkeypatch, php_constraint="~8.1.0||~8.2.0||~8.3.0", component_versions={})
    module = await _make_module(db_session, name="Vendor_Old", php_constraint="~7.4.0")
    await db_session.commit()

    try:
        response = await _get("2.4.7")
    finally:
        await _cleanup(db_session, module)

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "2.4.7"
    assert body["checked_count"] == 1
    assert len(body["blocked_modules"]) == 1
    entry = body["blocked_modules"][0]
    assert entry["module_id"] == module.id
    assert entry["findings"][0]["check_type"] == "magento_php_incompatible"
    assert entry["findings"][0]["severity"] == "blocking"


@pytest.mark.asyncio
async def test_flags_a_module_incompatible_on_a_magento_package_version(db_session, monkeypatch):
    _patch_release(
        monkeypatch, php_constraint="~8.1.0", component_versions={"magento/module-sales": "103.0.5"}
    )
    module = await _make_module(db_session, name="Vendor_Sales", php_constraint="~8.1.0")
    db_session.add(
        ComposerPackageRequirement(
            module_id=module.id, package_name="magento/module-sales", constraint="^100.0", is_dev=False
        )
    )
    await db_session.commit()

    try:
        response = await _get("2.4.7")
    finally:
        await _cleanup(db_session, module)

    body = response.json()
    assert len(body["blocked_modules"]) == 1
    finding = body["blocked_modules"][0]["findings"][0]
    assert finding["check_type"] == "magento_version_blocker"
    assert "magento/module-sales" in finding["message"]


@pytest.mark.asyncio
async def test_a_fully_compatible_module_is_not_in_blocked_modules(db_session, monkeypatch):
    _patch_release(
        monkeypatch, php_constraint="~8.1.0", component_versions={"magento/module-sales": "103.0.5"}
    )
    module = await _make_module(db_session, name="Vendor_Clean", php_constraint="~8.1.0")
    db_session.add(
        ComposerPackageRequirement(
            module_id=module.id, package_name="magento/module-sales", constraint="^103.0", is_dev=False
        )
    )
    await db_session.commit()

    try:
        response = await _get("2.4.7")
    finally:
        await _cleanup(db_session, module)

    body = response.json()
    assert body["checked_count"] == 1
    assert body["blocked_modules"] == []


@pytest.mark.asyncio
async def test_an_unrecognized_version_returns_404(db_session, monkeypatch):
    _patch_release(monkeypatch, php_constraint=None, component_versions={})
    module = await _make_module(db_session, name="Vendor_Clean", php_constraint="~8.1.0")
    await db_session.commit()

    try:
        response = await _get("9.9.9-does-not-exist")
    finally:
        await _cleanup(db_session, module)

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_repo_root_with_no_scanned_modules_returns_404(db_session, monkeypatch):
    _patch_release(monkeypatch, php_constraint="~8.1.0", component_versions={})

    response = await _get("2.4.7", repo_root="/tmp/nonexistent-repo-root")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_real_unmocked_fetch_calls_do_not_touch_the_session_concurrently(db_session):
    """Regression test for a real bug this endpoint shipped with once:
    fetching target_php_constraint and component_versions via
    asyncio.gather() raised sqlalchemy.exc.IllegalStateChangeError, since
    both calls read/write the same shared AsyncSession through
    packagist_cache's get_cached/set_cached, and AsyncSession doesn't
    support concurrent use from multiple coroutines (see
    app/scanner/packagist_cache.py's own fetch_many_with_cache docstring on
    this exact constraint). Deliberately does NOT monkeypatch
    fetch_release_php_constraint/fetch_release_component_versions -- a mock
    that never touches `session` can't reproduce this, which is exactly how
    the bug shipped unnoticed past every other test in this file.
    """
    tag = "2.4.9-test-only"
    await db_session.execute(
        delete(PackagistCache).where(PackagistCache.cache_key == f"magento-github:{tag}:composer.json")
    )
    db_session.add(
        PackagistCache(
            cache_key=f"magento-github:{tag}:composer.json",
            response_json={"require": {"php": "~8.1.0"}, "replace": {"magento/module-sales": "103.0.5"}},
            fetched_at=datetime.now(UTC),
        )
    )
    module = await _make_module(db_session, name="Vendor_Real", php_constraint="~7.4.0")
    await db_session.commit()

    try:
        response = await _get(tag)
    finally:
        await _cleanup(db_session, module)

    assert response.status_code == 200
    body = response.json()
    assert len(body["blocked_modules"]) == 1
    assert body["blocked_modules"][0]["findings"][0]["check_type"] == "magento_php_incompatible"
