import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


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
async def test_chat_streams_sources_token_done_in_order(monkeypatch):
    async def fake_run_agent(session, messages, audience):
        yield {"event": "sources", "sources": [{"module_id": 1, "module_name": "Vendor_Module", "relative_path": None}]}
        yield {"event": "token", "text": "Hello"}
        yield {"event": "token", "text": " world"}
        yield {"event": "done", "tokens_in": 10, "tokens_out": 5, "cost_usd": "0.001"}

    monkeypatch.setattr("app.api.routes.chat.run_agent", fake_run_agent)

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        client.stream(
            "POST",
            "/chat",
            json={"messages": [{"role": "user", "content": "hi"}], "audience": "dev"},
        ) as response,
    ):
        assert response.status_code == 200
        raw_text = ""
        async for chunk in response.aiter_text():
            raw_text += chunk

    events = _parse_sse(raw_text)
    event_types = [e[0] for e in events]
    assert event_types == ["sources", "token", "token", "done"]
    assert "Vendor_Module" in events[0][1]
    assert "Hello" in events[1][1]


@pytest.mark.asyncio
async def test_chat_streams_error_event_on_budget_exceeded(monkeypatch):
    async def fake_run_agent(session, messages, audience):
        yield {"event": "error", "detail": "Monthly LLM budget exceeded — cannot answer right now."}

    monkeypatch.setattr("app.api.routes.chat.run_agent", fake_run_agent)

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        client.stream(
            "POST",
            "/chat",
            json={"messages": [{"role": "user", "content": "hi"}], "audience": "pm"},
        ) as response,
    ):
        raw_text = ""
        async for chunk in response.aiter_text():
            raw_text += chunk

    events = _parse_sse(raw_text)
    assert events == [("error", '{"detail": "Monthly LLM budget exceeded \\u2014 cannot answer right now."}')]


@pytest.mark.asyncio
async def test_chat_rejects_unknown_audience_falls_back_to_dev(monkeypatch):
    seen_audience = {}

    async def fake_run_agent(session, messages, audience):
        seen_audience["value"] = audience
        yield {"event": "done", "tokens_in": 0, "tokens_out": 0, "cost_usd": "0"}

    monkeypatch.setattr("app.api.routes.chat.run_agent", fake_run_agent)

    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        client.stream(
            "POST",
            "/chat",
            json={"messages": [{"role": "user", "content": "hi"}], "audience": "nonsense"},
        ) as response,
    ):
        async for _ in response.aiter_text():
            pass

    assert seen_audience["value"] == "dev"
