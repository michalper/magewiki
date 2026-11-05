import hashlib
import hmac
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app

TEST_SECRET = "test-webhook-secret"


def _sign(body: bytes, secret: str = TEST_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def _configure_secret(monkeypatch):
    monkeypatch.setattr(settings, "webhook_hmac_secret", TEST_SECRET)


@pytest.mark.asyncio
async def test_webhook_scan_enqueues_with_valid_signature(demo_store_path):
    body = json.dumps({"path": str(demo_store_path.resolve())}).encode()
    signature = _sign(body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/scan",
            content=body,
            headers={"Content-Type": "application/json", "X-Signature-256": signature},
        )

    assert response.status_code == 202
    assert response.json()["status"] in ("enqueued", "duplicate")


@pytest.mark.asyncio
async def test_webhook_scan_rejects_invalid_signature(demo_store_path):
    body = json.dumps({"path": str(demo_store_path.resolve())}).encode()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/scan",
            content=body,
            headers={"Content-Type": "application/json", "X-Signature-256": "sha256=deadbeef"},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_scan_rejects_missing_signature(demo_store_path):
    body = json.dumps({"path": str(demo_store_path.resolve())}).encode()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/scan", content=body, headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_webhook_scan_rejects_nonexistent_path():
    body = json.dumps({"path": "/no/such/path"}).encode()
    signature = _sign(body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/scan",
            content=body,
            headers={"Content-Type": "application/json", "X-Signature-256": signature},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_webhook_scan_returns_503_when_not_configured(demo_store_path, monkeypatch):
    monkeypatch.setattr(settings, "webhook_hmac_secret", "")
    body = json.dumps({"path": str(demo_store_path.resolve())}).encode()
    signature = _sign(body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/webhooks/scan",
            content=body,
            headers={"Content-Type": "application/json", "X-Signature-256": signature},
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_webhook_scan_debounces_duplicate_calls(demo_store_path):
    body = json.dumps({"path": str(demo_store_path.resolve())}).encode()
    signature = _sign(body)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/webhooks/scan",
            content=body,
            headers={"Content-Type": "application/json", "X-Signature-256": signature},
        )
        second = await client.post(
            "/webhooks/scan",
            content=body,
            headers={"Content-Type": "application/json", "X-Signature-256": signature},
        )

    assert first.status_code == 202
    assert second.status_code == 202
    # arq's _job_id dedup checks both the pending job and its retained result, so
    # the second, identical call is debounced whether or not a worker ever drains
    # the first one during this test.
    assert second.json()["status"] == "duplicate"
