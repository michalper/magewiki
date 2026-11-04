from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_scan_and_list_modules(demo_store_path: Path):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scan_response = await client.post("/scan", json={"path": str(demo_store_path.resolve())})
        assert scan_response.status_code == 200
        scan_body = scan_response.json()
        assert scan_body["modules_found"] == 1
        assert scan_body["classes_total"] == 2
        assert scan_body["plugins_total"] == 1
        assert scan_body["observers_total"] == 1

        list_response = await client.get("/modules")
        assert list_response.status_code == 200
        modules = list_response.json()
        vendor_module = next(m for m in modules if m["name"] == "Vendor_Module")
        assert vendor_module["composer_name"] == "vendor/module-sample"
        assert vendor_module["enabled"] is True
        assert vendor_module["class_count"] == 2
        assert vendor_module["plugin_count"] == 1
        assert vendor_module["observer_count"] == 1

        detail_response = await client.get(f"/modules/{vendor_module['id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["dependencies"] == ["Magento_Sales"]
        assert len(detail["classes"]) == 2


@pytest.mark.asyncio
async def test_scan_rejects_nonexistent_path():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/scan", json={"path": "/no/such/path"})

    assert response.status_code == 400
