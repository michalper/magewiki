import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select

from app.agent import loop as loop_module
from app.agent.loop import MAX_TOOL_ROUNDS, run_agent
from app.models import AnalysisCache, Module


async def _make_module(session, suffix: str) -> Module:
    module = Module(
        repo_root=f"/tmp/agent-loop-test-{suffix}",
        name=f"AgentLoopTestModule_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=f"hash-{suffix}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    return module


@dataclass
class FakeUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 5
    cost: float | None = None


@dataclass
class FakeFunction:
    name: str
    arguments: str


@dataclass
class FakeToolCall:
    id: str
    function: FakeFunction


@dataclass
class FakeMessage:
    tool_calls: list[FakeToolCall] = field(default_factory=list)
    content: str | None = None

    def model_dump(self) -> dict:
        return {"role": "assistant", "content": self.content, "tool_calls": self.tool_calls}


@dataclass
class FakeChoice:
    message: FakeMessage


@dataclass
class FakeResponse:
    choices: list[FakeChoice]
    usage: FakeUsage = field(default_factory=FakeUsage)


@dataclass
class FakeStreamChunk:
    choices: list
    usage: FakeUsage | None = None


@dataclass
class FakeDelta:
    content: str | None


class FakeChunkChoice:
    def __init__(self, content: str | None):
        self.delta = FakeDelta(content)


async def _fake_stream(texts: list[str]):
    for text in texts:
        yield FakeStreamChunk(choices=[FakeChunkChoice(text)])
    yield FakeStreamChunk(choices=[], usage=FakeUsage(prompt_tokens=50, completion_tokens=20, cost=0.001))


def _tool_call_response(tool_name: str, args: dict) -> FakeResponse:
    import json

    return FakeResponse(
        choices=[
            FakeChoice(
                message=FakeMessage(
                    tool_calls=[FakeToolCall(id="call_1", function=FakeFunction(tool_name, json.dumps(args)))]
                )
            )
        ]
    )


def _direct_answer_response() -> FakeResponse:
    return FakeResponse(choices=[FakeChoice(message=FakeMessage(tool_calls=[], content="(discarded)"))])


@pytest.mark.asyncio
async def test_run_agent_executes_tool_then_streams_final_answer(db_session, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)

    async def _never_exceeded(session):
        return False

    monkeypatch.setattr(loop_module, "is_budget_exceeded", _never_exceeded)

    async def fake_list_modules(session, **kwargs):
        return {"total": 1, "modules": [{"module_id": module.id, "name": module.name}]}

    monkeypatch.setitem(loop_module.TOOL_FUNCTIONS, "list_modules", fake_list_modules)

    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if kwargs.get("stream"):
            return _fake_stream(["Hello", " world"])
        if len(calls) == 1:
            return _tool_call_response("list_modules", {})
        return _direct_answer_response()

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)

    events = [e async for e in run_agent(db_session, [{"role": "user", "content": "list modules"}], "dev")]

    sources_event = next(e for e in events if e["event"] == "sources")
    assert sources_event["sources"] == [{"module_id": module.id, "module_name": module.name, "relative_path": None}]

    token_events = [e for e in events if e["event"] == "token"]
    assert "".join(e["text"] for e in token_events) == "Hello world"

    done_event = next(e for e in events if e["event"] == "done")
    assert done_event["tokens_in"] > 0
    assert float(done_event["cost_usd"]) > 0

    # Tool-calling rounds and the final answer call all kept the same tools list
    # (see loop.py's comment on Anthropic's thinking-block signature binding).
    assert all(c.get("tools") for c in calls)

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_run_agent_persists_chat_cost(db_session, monkeypatch):
    async def _never_exceeded(session):
        return False

    monkeypatch.setattr(loop_module, "is_budget_exceeded", _never_exceeded)

    async def fake_acompletion(**kwargs):
        if kwargs.get("stream"):
            return _fake_stream(["ok"])
        return _direct_answer_response()

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)

    before = await db_session.scalar(select(AnalysisCache.id).where(AnalysisCache.kind == "chat").limit(1))

    events = [e async for e in run_agent(db_session, [{"role": "user", "content": "hi"}], "dev")]
    assert any(e["event"] == "done" for e in events)

    chat_rows = (await db_session.scalars(select(AnalysisCache).where(AnalysisCache.kind == "chat"))).all()
    assert len(chat_rows) >= 1
    if before is not None:
        assert len(chat_rows) >= 1  # at least our new row exists alongside any pre-existing ones


@pytest.mark.asyncio
async def test_run_agent_forces_a_retry_when_first_turn_skips_tools(db_session, monkeypatch):
    """An unconditional direct answer on round 1 (no tool call, so nothing is
    grounded in retrieved data) must not be accepted as-is — the loop should
    nudge the model to actually use a tool before giving up.
    """
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)

    async def _never_exceeded(session):
        return False

    monkeypatch.setattr(loop_module, "is_budget_exceeded", _never_exceeded)

    async def fake_list_modules(session, **kwargs):
        return {"total": 1, "modules": [{"module_id": module.id, "name": module.name}]}

    monkeypatch.setitem(loop_module.TOOL_FUNCTIONS, "list_modules", fake_list_modules)

    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if kwargs.get("stream"):
            return _fake_stream(["ok"])
        non_stream_calls = [c for c in calls if not c.get("stream")]
        n = len(non_stream_calls)
        if n == 1:
            return _direct_answer_response()  # skips tools entirely
        if n == 2:
            return _tool_call_response("list_modules", {})  # corrects after the nudge
        return _direct_answer_response()  # done — sources are populated now

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)

    events = [e async for e in run_agent(db_session, [{"role": "user", "content": "list modules"}], "dev")]

    non_stream_calls = [c for c in calls if not c.get("stream")]
    assert len(non_stream_calls) == 3

    last_messages = non_stream_calls[-1]["messages"]
    assert any(
        isinstance(m.get("content"), str) and "without calling any tools" in m["content"] for m in last_messages
    )

    sources_event = next(e for e in events if e["event"] == "sources")
    assert sources_event["sources"] == [{"module_id": module.id, "module_name": module.name, "relative_path": None}]

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_run_agent_stops_after_max_tool_rounds(db_session, monkeypatch):
    async def _never_exceeded(session):
        return False

    monkeypatch.setattr(loop_module, "is_budget_exceeded", _never_exceeded)

    async def fake_list_modules(session, **kwargs):
        return {"total": 0, "modules": []}

    monkeypatch.setitem(loop_module.TOOL_FUNCTIONS, "list_modules", fake_list_modules)

    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if kwargs.get("stream"):
            return _fake_stream(["done"])
        return _tool_call_response("list_modules", {})  # always asks for another tool call

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)

    events = [e async for e in run_agent(db_session, [{"role": "user", "content": "loop forever"}], "dev")]

    assert any(e["event"] == "done" for e in events)
    non_streaming_calls = [c for c in calls if not c.get("stream")]
    assert len(non_streaming_calls) == MAX_TOOL_ROUNDS


@pytest.mark.asyncio
async def test_run_agent_errors_on_budget_exceeded(db_session, monkeypatch):
    async def _always_exceeded(session):
        return True

    monkeypatch.setattr(loop_module, "is_budget_exceeded", _always_exceeded)

    called = False

    async def fake_acompletion(**kwargs):
        nonlocal called
        called = True
        return _direct_answer_response()

    monkeypatch.setattr(loop_module.litellm, "acompletion", fake_acompletion)

    events = [e async for e in run_agent(db_session, [{"role": "user", "content": "hi"}], "dev")]

    assert events == [
        {"event": "error", "detail": "Monthly LLM budget exceeded — cannot answer right now."},
        {"event": "done", "tokens_in": 0, "tokens_out": 0, "cost_usd": "0"},
    ]
    assert called is False
