import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from app.evaluation.faithfulness import (
    FaithfulnessVerdict,
    build_faithfulness_judge_prompt,
    fetch_cited_source_texts,
    judge_faithfulness,
)
from app.models import Chunk, Module


def _vector() -> list[float]:
    return [0.0] * 1536


async def _make_module(session, suffix: str) -> Module:
    module = Module(
        repo_root=f"/tmp/faithfulness-test-{suffix}",
        name=f"FaithfulnessTestModule_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=f"hash-{suffix}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    return module


def _tool_response(data: dict) -> SimpleNamespace:
    tool_call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(data)))
    message = SimpleNamespace(tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.mark.asyncio
async def test_fetch_cited_source_texts_resolves_module_and_file_level_chunks(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)
    module_chunk = Chunk(
        module_id=module.id, chunk_type="module", relative_path=None,
        content_hash=f"mod-{suffix}", text="module-level summary text", embedding=_vector(),
    )
    file_chunk = Chunk(
        module_id=module.id, chunk_type="file", relative_path="Foo.php",
        content_hash=f"file-{suffix}", text="file-level source text", embedding=_vector(),
    )
    db_session.add_all([module_chunk, file_chunk])
    await db_session.commit()

    sources = [
        {"module_id": module.id, "module_name": module.name, "relative_path": None},
        {"module_id": module.id, "module_name": module.name, "relative_path": "Foo.php"},
    ]

    texts = await fetch_cited_source_texts(db_session, sources)

    assert ("FaithfulnessTestModule_" + suffix, "module-level summary text") in texts
    assert (f"FaithfulnessTestModule_{suffix} / Foo.php", "file-level source text") in texts

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_fetch_cited_source_texts_deduplicates_the_same_source_cited_twice(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)
    chunk = Chunk(
        module_id=module.id, chunk_type="file", relative_path="Bar.php",
        content_hash=f"bar-{suffix}", text="bar text", embedding=_vector(),
    )
    db_session.add(chunk)
    await db_session.commit()

    sources = [
        {"module_id": module.id, "module_name": module.name, "relative_path": "Bar.php"},
        {"module_id": module.id, "module_name": module.name, "relative_path": "Bar.php"},
    ]

    texts = await fetch_cited_source_texts(db_session, sources)

    assert texts == [(f"FaithfulnessTestModule_{suffix} / Bar.php", "bar text")]

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_fetch_cited_source_texts_skips_a_source_with_no_module_id(db_session):
    assert await fetch_cited_source_texts(db_session, [{"module_id": None}]) == []


def test_build_faithfulness_judge_prompt_includes_question_answer_and_sources():
    prompt = build_faithfulness_judge_prompt(
        "does it send SMS?", "Yes, via Twilio.", [("Vendor_Module / Sms.php", "class uses Twilio API")]
    )
    assert "does it send SMS?" in prompt
    assert "Yes, via Twilio." in prompt
    assert "Vendor_Module / Sms.php" in prompt
    assert "class uses Twilio API" in prompt


def test_build_faithfulness_judge_prompt_notes_when_there_are_no_sources():
    prompt = build_faithfulness_judge_prompt("q", "a", [])
    assert "none" in prompt.lower()


@pytest.mark.asyncio
async def test_judge_faithfulness_returns_a_grounded_verdict(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _tool_response({"grounded": True, "unsupported_claims": [], "reasoning": "matches the source"})

    monkeypatch.setattr("app.evaluation.faithfulness.litellm.acompletion", fake_acompletion)

    verdict = await judge_faithfulness(
        None, "q", "a", [], model="anthropic/claude-haiku-5-5", api_key="k"
    )

    assert verdict == FaithfulnessVerdict(grounded=True, unsupported_claims=[], reasoning="matches the source")


@pytest.mark.asyncio
async def test_judge_faithfulness_returns_an_unsupported_verdict_with_claims(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _tool_response(
            {"grounded": False, "unsupported_claims": ["claims Redis caching, sources never mention it"],
             "reasoning": "one claim has no backing source"}
        )

    monkeypatch.setattr("app.evaluation.faithfulness.litellm.acompletion", fake_acompletion)

    verdict = await judge_faithfulness(None, "q", "a", [], model="m", api_key="k")

    assert verdict.grounded is False
    assert verdict.unsupported_claims == ["claims Redis caching, sources never mention it"]


@pytest.mark.asyncio
async def test_judge_faithfulness_raises_when_the_provider_returns_no_tool_call(monkeypatch):
    async def fake_acompletion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=None))])

    monkeypatch.setattr("app.evaluation.faithfulness.litellm.acompletion", fake_acompletion)

    with pytest.raises(RuntimeError, match="did not return a verdict"):
        await judge_faithfulness(None, "q", "a", [], model="m", api_key="k")


@pytest.mark.asyncio
async def test_judge_faithfulness_raises_on_a_schema_invalid_response(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _tool_response({"unsupported_claims": []})  # missing required 'grounded'/'reasoning'

    monkeypatch.setattr("app.evaluation.faithfulness.litellm.acompletion", fake_acompletion)

    with pytest.raises(Exception):  # noqa: B017,PT011 - any pydantic ValidationError shape is fine here
        await judge_faithfulness(None, "q", "a", [], model="m", api_key="k")
