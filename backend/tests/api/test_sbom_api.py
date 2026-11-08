import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db import async_session_factory
from app.main import app
from app.models import ComposerPackageRequirement, Module


@pytest.fixture
async def sbom_fixture(db_session):
    suffix = uuid.uuid4().hex[:8]
    repo_root = f"/tmp/repo-sbom-{suffix}"

    module = Module(
        repo_root=repo_root,
        name=f"Vendor_Module_{suffix}",
        composer_name=f"vendor/module-{suffix}",
        setup_version="1.2.3",
        license=["OSL-3.0"],
        homepage="https://example.com",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash="h1",
        enabled=True,
        last_scanned_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db_session.add(module)
    await db_session.commit()

    yield repo_root, module

    async with async_session_factory() as cleanup_session:
        await cleanup_session.execute(delete(Module).where(Module.id == module.id))
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_get_repo_sbom_returns_a_cyclonedx_document(sbom_fixture):
    repo_root, module = sbom_fixture

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/repos/sbom", params={"repo_root": repo_root})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.cyclonedx+json")
    assert "attachment" in response.headers["content-disposition"]

    body = response.json()
    assert body["bomFormat"] == "CycloneDX"
    assert len(body["components"]) == 1
    component = body["components"][0]
    assert component["name"] == module.composer_name
    assert component["version"] == "1.2.3"
    assert component["licenses"] == [{"license": {"name": "OSL-3.0"}}]
    assert "dependencies" not in body


@pytest.mark.asyncio
async def test_get_repo_sbom_includes_production_requirements_as_a_dependency_graph(sbom_fixture):
    repo_root, module = sbom_fixture

    async with async_session_factory() as session:
        session.add_all(
            [
                ComposerPackageRequirement(
                    module_id=module.id, package_name="guzzlehttp/guzzle", constraint="^7.0", is_dev=False
                ),
                ComposerPackageRequirement(
                    module_id=module.id, package_name="phpunit/phpunit", constraint="^9.0", is_dev=True
                ),
            ]
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/repos/sbom", params={"repo_root": repo_root})

    body = response.json()
    names = {c["name"] for c in body["components"]}
    assert "guzzlehttp/guzzle" in names
    assert "phpunit/phpunit" not in names  # dev-only requirements are excluded
    assert body["dependencies"] == [{"ref": module.composer_name, "dependsOn": ["guzzlehttp/guzzle"]}]


@pytest.mark.asyncio
async def test_get_repo_sbom_404s_for_an_unknown_repo_root():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/repos/sbom", params={"repo_root": "/tmp/does-not-exist"})

    assert response.status_code == 404
