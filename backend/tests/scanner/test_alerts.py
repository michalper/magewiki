import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.scanner.alerts import (
    FindingIncrease,
    ModuleAlert,
    compute_alert_increases,
    send_quality_alert,
)

ALERTABLE = ("hardcoded_secret", "security_advisory")


def test_first_scan_with_no_previous_snapshot_still_alerts():
    increases = compute_alert_increases(None, {"hardcoded_secret": 1}, ALERTABLE)
    assert increases == [FindingIncrease(check_type="hardcoded_secret", previous_count=0, current_count=1)]


def test_a_real_increase_in_an_alertable_check_type_alerts():
    increases = compute_alert_increases({"hardcoded_secret": 1}, {"hardcoded_secret": 3}, ALERTABLE)
    assert increases == [FindingIncrease(check_type="hardcoded_secret", previous_count=1, current_count=3)]


def test_a_decrease_never_alerts():
    increases = compute_alert_increases({"hardcoded_secret": 3}, {"hardcoded_secret": 1}, ALERTABLE)
    assert increases == []


def test_an_increase_in_a_non_alertable_check_type_is_ignored():
    increases = compute_alert_increases({"phpstan_error": 1}, {"phpstan_error": 50}, ALERTABLE)
    assert increases == []


def test_multiple_simultaneous_increases_are_all_reported():
    increases = compute_alert_increases(
        {"hardcoded_secret": 0, "security_advisory": 1},
        {"hardcoded_secret": 2, "security_advisory": 4},
        ALERTABLE,
    )
    assert increases == [
        FindingIncrease(check_type="hardcoded_secret", previous_count=0, current_count=2),
        FindingIncrease(check_type="security_advisory", previous_count=1, current_count=4),
    ]


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
async def test_no_webhook_call_when_there_are_no_module_alerts(monkeypatch):
    client = _FakeAsyncClient()
    monkeypatch.setattr("app.scanner.alerts.httpx.AsyncClient", lambda *a, **k: client)

    await send_quality_alert("https://example.com/webhook", "/repo", [])

    assert client.posted_url is None


@pytest.mark.asyncio
async def test_no_webhook_call_when_the_url_is_empty(monkeypatch):
    client = _FakeAsyncClient()
    monkeypatch.setattr("app.scanner.alerts.httpx.AsyncClient", lambda *a, **k: client)
    module_alerts = [
        ModuleAlert(
            module_id=1,
            module_name="Vendor_Module",
            increases=[FindingIncrease(check_type="hardcoded_secret", previous_count=0, current_count=1)],
        )
    ]

    await send_quality_alert("", "/repo", module_alerts)

    assert client.posted_url is None


@pytest.mark.asyncio
async def test_sends_exactly_one_post_with_the_expected_payload_shape(monkeypatch):
    client = _FakeAsyncClient()
    monkeypatch.setattr("app.scanner.alerts.httpx.AsyncClient", lambda *a, **k: client)
    module_alerts = [
        ModuleAlert(
            module_id=1,
            module_name="Vendor_Module",
            increases=[FindingIncrease(check_type="hardcoded_secret", previous_count=0, current_count=1)],
        )
    ]

    await send_quality_alert("https://example.com/webhook", "/repo", module_alerts)

    assert client.posted_url == "https://example.com/webhook"
    assert client.posted_json["event"] == "quality_alert"
    assert client.posted_json["repo_root"] == "/repo"
    assert "Vendor_Module" in client.posted_json["text"]
    assert client.posted_json["modules"] == [
        {
            "module_id": 1,
            "module_name": "Vendor_Module",
            "increases": [{"check_type": "hardcoded_secret", "previous_count": 0, "current_count": 1}],
        }
    ]


@pytest.mark.asyncio
async def test_an_http_error_is_swallowed_not_raised(monkeypatch):
    client = _FakeAsyncClient(raise_error=True)
    monkeypatch.setattr("app.scanner.alerts.httpx.AsyncClient", lambda *a, **k: client)
    module_alerts = [
        ModuleAlert(
            module_id=1,
            module_name="Vendor_Module",
            increases=[FindingIncrease(check_type="hardcoded_secret", previous_count=0, current_count=1)],
        )
    ]

    await send_quality_alert("https://example.com/webhook", "/repo", module_alerts)  # must not raise


# --- Real network delivery, not a fake httpx client -- a real socket, a
# real HTTP server in a background thread, actually receiving the POST. The
# tests above prove the payload shape and the fail-open contract against a
# mocked transport; these two prove send_quality_alert actually talks real
# HTTP correctly, both when something is listening and when nothing is. ---


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
            pass  # silence BaseHTTPRequestHandler's default stderr access log

    server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}/hook", received
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.mark.asyncio
async def test_a_real_http_post_is_actually_delivered(real_webhook_server):
    url, received = real_webhook_server
    module_alerts = [
        ModuleAlert(
            module_id=1,
            module_name="Vendor_Module",
            increases=[FindingIncrease(check_type="hardcoded_secret", previous_count=0, current_count=1)],
        )
    ]

    await send_quality_alert(url, "/repo", module_alerts)

    assert len(received) == 1
    assert received[0]["event"] == "quality_alert"
    assert received[0]["repo_root"] == "/repo"
    assert "Vendor_Module" in received[0]["text"]
    assert received[0]["modules"][0]["increases"][0]["check_type"] == "hardcoded_secret"


@pytest.mark.asyncio
async def test_a_real_connection_failure_is_swallowed_not_raised():
    # Bind to grab a free port, then close it immediately -- nothing
    # listens there, so the connection attempt is a genuine, fast refusal,
    # not a mocked error or a slow timeout.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    module_alerts = [
        ModuleAlert(
            module_id=1,
            module_name="Vendor_Module",
            increases=[FindingIncrease(check_type="hardcoded_secret", previous_count=0, current_count=1)],
        )
    ]

    await send_quality_alert(f"http://127.0.0.1:{port}/hook", "/repo", module_alerts)  # must not raise
