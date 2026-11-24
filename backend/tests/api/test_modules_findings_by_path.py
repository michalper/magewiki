from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.main import app
from app.models import Module, ModuleQualityFinding

REPO_ROOT = "/tmp/pr-gate-test-repo"
OTHER_REPO_ROOT = "/tmp/pr-gate-test-repo-other"


async def _make_module(db_session, *, name: str, path: str, repo_root: str = REPO_ROOT) -> Module:
    module = Module(
        repo_root=repo_root,
        name=name,
        path=path,
        source_type="standalone",
        state="up_to_date",
        enabled=True,
        current_hash=f"hash-{name}",
        last_scanned_at=datetime.now(UTC),
    )
    db_session.add(module)
    await db_session.flush()
    return module


async def _cleanup(db_session, *modules: Module) -> None:
    await db_session.execute(delete(Module).where(Module.id.in_([m.id for m in modules])))
    await db_session.commit()


async def _get(paths: list[str], repo_root: str = REPO_ROOT) -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/modules/findings-by-path",
            params={"repo_root": repo_root, "paths": ",".join(paths)},
        )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_matches_a_changed_file_to_its_module_and_returns_findings(db_session):
    module = await _make_module(db_session, name="Vendor_Foo", path="app/code/Vendor/Foo")
    db_session.add(
        ModuleQualityFinding(
            module_id=module.id,
            check_type="hardcoded_secret",
            severity="blocking",
            file_path="Model/Thing.php",
            line=12,
            message="looks like an API key",
        )
    )
    await db_session.commit()

    try:
        body = await _get(["app/code/Vendor/Foo/Model/Thing.php"])
    finally:
        await _cleanup(db_session, module)

    assert body["unmatched_paths"] == []
    assert len(body["modules"]) == 1
    entry = body["modules"][0]
    assert entry["module_id"] == module.id
    assert entry["name"] == "Vendor_Foo"
    assert entry["matched_paths"] == ["app/code/Vendor/Foo/Model/Thing.php"]
    assert entry["findings"] == [
        {
            "check_type": "hardcoded_secret",
            "severity": "blocking",
            "file_path": "Model/Thing.php",
            "line": 12,
            "message": "looks like an API key",
        }
    ]


@pytest.mark.asyncio
async def test_prefix_match_does_not_let_a_shorter_module_path_swallow_a_longer_sibling(db_session):
    short = await _make_module(db_session, name="Vendor_ModuleFoo", path="vendor/vendor/module-foo")
    long = await _make_module(db_session, name="Vendor_ModuleFooExtra", path="vendor/vendor/module-foo-extra")
    await db_session.commit()

    try:
        body = await _get(["vendor/vendor/module-foo-extra/Helper/Data.php"])
    finally:
        await _cleanup(db_session, short, long)

    assert body["unmatched_paths"] == []
    assert len(body["modules"]) == 1
    assert body["modules"][0]["module_id"] == long.id


@pytest.mark.asyncio
async def test_longest_matching_module_path_wins_over_a_root_module_fallback(db_session):
    root = await _make_module(db_session, name="Vendor_Root", path="")
    nested = await _make_module(db_session, name="Vendor_Nested", path="app/code/Vendor/Nested")
    await db_session.commit()

    try:
        nested_hit = await _get(["app/code/Vendor/Nested/Model/Thing.php"])
        root_hit = await _get(["composer.json"])
    finally:
        await _cleanup(db_session, root, nested)

    assert nested_hit["modules"][0]["module_id"] == nested.id
    assert root_hit["modules"][0]["module_id"] == root.id


@pytest.mark.asyncio
async def test_a_path_matching_no_module_is_reported_as_unmatched(db_session):
    module = await _make_module(db_session, name="Vendor_Foo", path="app/code/Vendor/Foo")
    await db_session.commit()

    try:
        body = await _get(["README.md"])
    finally:
        await _cleanup(db_session, module)

    assert body["modules"] == []
    assert body["unmatched_paths"] == ["README.md"]


@pytest.mark.asyncio
async def test_findings_are_scoped_to_the_requested_repo_root(db_session):
    here = await _make_module(db_session, name="Vendor_Foo", path="app/code/Vendor/Foo", repo_root=REPO_ROOT)
    elsewhere = await _make_module(
        db_session, name="Vendor_Foo", path="app/code/Vendor/Foo", repo_root=OTHER_REPO_ROOT
    )
    await db_session.commit()

    try:
        body = await _get(["app/code/Vendor/Foo/Model/Thing.php"], repo_root=OTHER_REPO_ROOT)
    finally:
        await _cleanup(db_session, here, elsewhere)

    assert len(body["modules"]) == 1
    assert body["modules"][0]["module_id"] == elsewhere.id


@pytest.mark.asyncio
async def test_a_module_with_no_findings_is_still_reported_with_an_empty_list(db_session):
    module = await _make_module(db_session, name="Vendor_Clean", path="app/code/Vendor/Clean")
    await db_session.commit()

    try:
        body = await _get(["app/code/Vendor/Clean/Model/Thing.php"])
    finally:
        await _cleanup(db_session, module)

    assert body["modules"][0]["findings"] == []
