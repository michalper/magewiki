import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models import AnalysisCache, Module, ModuleDocument
from tests.conftest import delete_module_if_present


@pytest.mark.asyncio
async def test_scan_and_list_modules(demo_store_path: Path, db_session: AsyncSession):
    # This test creates its own ModuleDocument below, assuming none already exists
    # for this module — true by construction only if nothing else left one behind
    # for the same (repo_root, name); enforce that rather than assume it.
    await delete_module_if_present(db_session, str(demo_store_path.resolve()), "Vendor_Module")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scan_response = await client.post("/scan", json={"path": str(demo_store_path.resolve())})
        assert scan_response.status_code == 200
        scan_body = scan_response.json()
        assert scan_body["modules_found"] == 1
        assert scan_body["classes_total"] == 2
        assert scan_body["plugins_total"] == 1
        assert scan_body["observers_total"] == 1

        # Resolve the module authoritatively by repo_root, not by name: other
        # tests (e.g. scanner tests using tmp_path) can leave behind unrelated
        # modules also named "Vendor_Module", and the /modules list order must
        # not be relied on to pick the right one.
        db_module = await db_session.scalar(
            select(Module).where(Module.repo_root == str(demo_store_path.resolve()))
        )
        assert db_module is not None
        module_id = db_module.id

        list_response = await client.get("/modules")
        assert list_response.status_code == 200
        modules = list_response.json()
        vendor_module = next(m for m in modules if m["id"] == module_id)
        assert vendor_module["composer_name"] == "vendor/module-sample"
        assert vendor_module["setup_version"] == "1.0.0"
        assert vendor_module["enabled"] is True
        assert vendor_module["class_count"] == 2
        assert vendor_module["plugin_count"] == 1
        assert vendor_module["observer_count"] == 1
        assert vendor_module["tags"] == []

        detail_response = await client.get(f"/modules/{module_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["setup_version"] == "1.0.0"
        assert detail["dependencies"] == ["Magento_Sales"]
        assert len(detail["classes"]) == 2
        assert detail["tags"] == []

        content_hash = uuid.uuid4().hex
        cache = AnalysisCache(
            content_hash=content_hash,
            model="test-model",
            prompt_version="v1",
            kind="module_synthesis",
            response={},
            tokens_in=0,
            tokens_out=0,
            cost_usd=0,
        )
        db_session.add(cache)
        await db_session.flush()
        db_session.add(
            ModuleDocument(
                module_id=module_id,
                content_hash=content_hash,
                model="test-model",
                prompt_version="v1",
                cache_id=cache.id,
                doc={
                    "summary": "s",
                    "description": "d",
                    "confidence": 0.9,
                    "pm_text": "pm",
                    "dev_text": "dev",
                    "tags": [
                        {"name": "payments", "source": "parser", "confidence": 1.0},
                        {"name": "checkout", "source": "ai", "confidence": 0.8},
                    ],
                },
            )
        )
        await db_session.commit()

        list_response = await client.get("/modules")
        vendor_module = next(m for m in list_response.json() if m["id"] == module_id)
        assert vendor_module["tags"] == ["payments", "checkout"]

        detail_response = await client.get(f"/modules/{module_id}")
        assert detail_response.json()["tags"] == ["payments", "checkout"]

        await db_session.execute(delete(ModuleDocument).where(ModuleDocument.module_id == module_id))
        await db_session.commit()


@pytest.mark.asyncio
async def test_scan_rejects_nonexistent_path():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/scan", json={"path": "/no/such/path"})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_scan_rejects_a_real_directory_outside_every_configured_scan_root(tmp_path: Path, monkeypatch):
    """The actual security fix: a path that exists and is a real directory, but
    isn't under any configured scan root, must still be rejected — scan_roots was
    previously only used for UI/error-message text, never actually enforced.
    """
    outside = tmp_path / "outside-any-scan-root"
    outside.mkdir()
    monkeypatch.setattr("app.api.routes.modules.settings.magewiki_scan_root_1", str(tmp_path / "allowed-only"))
    monkeypatch.setattr("app.api.routes.modules.settings.magewiki_scan_root_2", "")
    monkeypatch.setattr("app.api.routes.modules.settings.magewiki_scan_root_3", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/scan", json={"path": str(outside)})

    assert response.status_code == 400
    assert "scan root" in response.json()["detail"]
