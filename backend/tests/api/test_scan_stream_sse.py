import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.scanner.orchestrator import ScanAlreadyInProgressError, ScanResult


def _parse_sse(raw_text: str) -> list[tuple[str, str]]:
    events = []
    for block in raw_text.strip("\n").split("\n\n"):
        if not block:
            continue
        lines = block.split("\n")
        event_type = lines[0].removeprefix("event: ")
        data = lines[1].removeprefix("data: ")
        events.append((event_type, data))
    return events


@pytest.mark.asyncio
async def test_scan_stream_relays_discovered_module_done_in_order(tmp_path, monkeypatch):
    async def fake_scan_repository_events(repo_root, session):
        yield {"event": "discovered", "total": 2}
        yield {"event": "module", "name": "Vendor_One", "status": "created", "index": 1, "total": 2, "warning": None}
        yield {"event": "module", "name": "Vendor_Two", "status": "created", "index": 2, "total": 2, "warning": None}
        yield {"event": "done", "result": ScanResult(repo_root=str(repo_root), modules_found=2, modules_created=2)}

    # tmp_path doesn't look like a store/module root, so scan_paths_events()
    # (now what the route actually calls) delegates straight through to
    # scan_repository_events() unchanged — patch it at its own module so the
    # delegation picks it up, the same way it did when the route imported it
    # directly.
    monkeypatch.setattr("app.scanner.orchestrator.scan_repository_events", fake_scan_repository_events)

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        client.stream("POST", "/scan/stream", json={"path": str(tmp_path)}) as response,
    ):
        assert response.status_code == 200
        raw_text = ""
        async for chunk in response.aiter_text():
            raw_text += chunk

    events = _parse_sse(raw_text)
    event_types = [e[0] for e in events]
    assert event_types == ["discovered", "module", "module", "done"]
    assert "Vendor_One" in events[1][1]
    assert "Vendor_Two" in events[2][1]
    assert '"modules_created": 2' in events[3][1]
    assert "duration_seconds" in events[3][1]


@pytest.mark.asyncio
async def test_scan_stream_relays_already_in_progress_as_an_error_event(tmp_path, monkeypatch):
    async def fake_scan_repository_events(repo_root, session):
        raise ScanAlreadyInProgressError(f"a scan of {repo_root} is already in progress")
        yield  # pragma: no cover - makes this an async generator function

    monkeypatch.setattr("app.scanner.orchestrator.scan_repository_events", fake_scan_repository_events)

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        client.stream("POST", "/scan/stream", json={"path": str(tmp_path)}) as response,
    ):
        raw_text = ""
        async for chunk in response.aiter_text():
            raw_text += chunk

    events = _parse_sse(raw_text)
    assert events[0][0] == "error"
    assert "already in progress" in events[0][1]


@pytest.mark.asyncio
async def test_scan_stream_relays_an_unexpected_exception_as_an_error_event(tmp_path, monkeypatch):
    # Previously, any exception other than ScanAlreadyInProgressError just dropped
    # the connection silently — the UI stayed on "Scanning..." forever with no
    # indication anything failed, defeating the whole point of this SSE redesign.
    async def fake_scan_repository_events(repo_root, session):
        yield {"event": "discovered", "total": 1}
        raise RuntimeError("boom")

    monkeypatch.setattr("app.scanner.orchestrator.scan_repository_events", fake_scan_repository_events)

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        client.stream("POST", "/scan/stream", json={"path": str(tmp_path)}) as response,
    ):
        raw_text = ""
        async for chunk in response.aiter_text():
            raw_text += chunk

    events = _parse_sse(raw_text)
    assert [e[0] for e in events] == ["discovered", "error"]
    assert "unexpectedly" in events[1][1]


@pytest.mark.asyncio
async def test_scan_stream_rejects_a_path_outside_any_mounted_scan_root():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/scan/stream", json={"path": "/definitely/not/a/real/directory"})

    assert response.status_code == 400
    assert "not a directory" in response.json()["detail"]
