import json
import socket
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.scanner.digest import send_fleet_digest
from app.search.fleet_digest import FleetDigest, FleetDigestModuleChange

WINDOW_START = datetime(2026, 11, 21, tzinfo=UTC)


class _FakeAsyncClient:
    def __init__(self, *, raise_error: bool = False):
        self.posted_url: str | None = None
        self.posted_json: dict | None = None
        self._raise_error = raise_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, **kwargs):
        self.posted_url = url
        self.posted_json = json
        return _FakeResponse(raise_error=self._raise_error)


class _FakeResponse:
    def __init__(self, *, raise_error: bool):
        self._raise_error = raise_error

    def raise_for_status(self) -> None:
        if self._raise_error:
            raise httpx.HTTPStatusError("boom", request=httpx.Request("POST", "http://x"), response=self)


@pytest.mark.asyncio
async def test_no_webhook_call_when_the_url_is_empty(monkeypatch):
    client = _FakeAsyncClient()
    monkeypatch.setattr("app.scanner.digest.httpx.AsyncClient", lambda *a, **k: client)
    digest = FleetDigest(window_start=WINDOW_START)

    await send_fleet_digest("", digest)

    assert client.posted_url is None


@pytest.mark.asyncio
async def test_a_quiet_week_still_posts_unlike_the_threshold_crossing_alert(monkeypatch):
    client = _FakeAsyncClient()
    monkeypatch.setattr("app.scanner.digest.httpx.AsyncClient", lambda *a, **k: client)
    digest = FleetDigest(window_start=WINDOW_START)

    await send_fleet_digest("https://example.com/webhook", digest)

    assert client.posted_url == "https://example.com/webhook"
    assert client.posted_json["event"] == "fleet_digest"
    assert client.posted_json["new_modules"] == []
    assert client.posted_json["changed_modules"] == []
    assert client.posted_json["total_delta"] == 0
    assert "no changes" in client.posted_json["text"].lower()


@pytest.mark.asyncio
async def test_sends_exactly_one_post_with_the_expected_payload_shape(monkeypatch):
    client = _FakeAsyncClient()
    monkeypatch.setattr("app.scanner.digest.httpx.AsyncClient", lambda *a, **k: client)
    digest = FleetDigest(
        window_start=WINDOW_START,
        new_modules=[(2, "Vendor_New")],
        changed_modules=[
            FleetDigestModuleChange(module_id=1, module_name="Vendor_Module", previous_total=1, current_total=3)
        ],
        total_delta=4,
    )

    await send_fleet_digest("https://example.com/webhook", digest)

    assert client.posted_url == "https://example.com/webhook"
    assert client.posted_json["window_start"] == WINDOW_START.isoformat()
    assert client.posted_json["new_modules"] == [{"module_id": 2, "module_name": "Vendor_New"}]
    assert client.posted_json["changed_modules"] == [
        {"module_id": 1, "module_name": "Vendor_Module", "previous_total": 1, "current_total": 3}
    ]
    assert client.posted_json["total_delta"] == 4
    assert "Vendor_New" in client.posted_json["text"]
    assert "Vendor_Module" in client.posted_json["text"]


@pytest.mark.asyncio
async def test_an_http_error_is_swallowed_not_raised(monkeypatch):
    client = _FakeAsyncClient(raise_error=True)
    monkeypatch.setattr("app.scanner.digest.httpx.AsyncClient", lambda *a, **k: client)
    digest = FleetDigest(window_start=WINDOW_START, total_delta=1)

    await send_fleet_digest("https://example.com/webhook", digest)  # must not raise


# --- Real network delivery, same house style as tests/scanner/test_alerts.py ---


@pytest.fixture
def real_webhook_server():
    received: list[dict] = []

    class _RecordingHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}/hook", received
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.asyncio
async def test_a_real_http_post_is_actually_delivered(real_webhook_server):
    url, received = real_webhook_server
    digest = FleetDigest(
        window_start=WINDOW_START,
        changed_modules=[
            FleetDigestModuleChange(module_id=1, module_name="Vendor_Module", previous_total=0, current_total=1)
        ],
        total_delta=1,
    )

    await send_fleet_digest(url, digest)

    assert len(received) == 1
    assert received[0]["event"] == "fleet_digest"
    assert received[0]["changed_modules"][0]["module_name"] == "Vendor_Module"


@pytest.mark.asyncio
async def test_a_real_connection_failure_is_swallowed_not_raised():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    digest = FleetDigest(window_start=WINDOW_START, total_delta=1)

    await send_fleet_digest(f"http://127.0.0.1:{port}/hook", digest)  # must not raise
