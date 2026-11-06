import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_get_scan_roots_reports_configured_settings(monkeypatch):
    monkeypatch.setattr(settings, "magewiki_scan_root_1", "/srv/repos")
    monkeypatch.setattr(settings, "magewiki_scan_root_2", "")
    monkeypatch.setattr(settings, "magewiki_scan_root_3", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/scan-roots")

    assert response.status_code == 200
    assert response.json() == {"scan_roots": ["/srv/repos"]}


@pytest.mark.asyncio
async def test_get_scan_roots_empty_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "magewiki_scan_root_1", "")
    monkeypatch.setattr(settings, "magewiki_scan_root_2", "")
    monkeypatch.setattr(settings, "magewiki_scan_root_3", "")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/scan-roots")

    assert response.status_code == 200
    assert response.json() == {"scan_roots": []}
