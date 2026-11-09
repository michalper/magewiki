import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.evaluation.dataset import (
    MODULE_ID_PLACEHOLDER,
    MODULE_SENTINEL,
    EnumerationQuestion,
    NegativeQuestion,
    RetrievalQuestion,
)
from app.evaluation.runner import (
    EvalReport,
    QuestionResult,
    _relevant_chunk_ids,
    _resolve_kwargs,
    run_faithfulness_eval,
    seed_corpus,
)
from app.models import Chunk, Module
from tests.conftest import fake_summarize_file, scan_demo_store
from tests.tasks.test_jobs_embed_chunks import _fake_doc, _fake_embed_text


@pytest.mark.asyncio
async def test_seed_corpus_drives_the_real_pipeline_to_up_to_date(demo_store_path: Path, db_session, monkeypatch):
    """Zero-cost: every LLM/embedding boundary is monkeypatched, same technique
    as the individual tasks/jobs.py tests — this exercises seed_corpus()'s own
    orchestration (wipe -> scan -> analyze every pending file -> synthesize ->
    embed) end to end, which no existing test drives directly (only the real,
    CI-excluded Ordo fixture test does).
    """
    async def _never_exceeded(session):
        return False

    monkeypatch.setattr("app.tasks.jobs.is_budget_exceeded", _never_exceeded)
    monkeypatch.setattr("app.tasks.jobs.summarize_file", fake_summarize_file())

    async def _fake_synthesize(facts, known_sources, known_config_paths, **kwargs):
        result_doc = _fake_doc()
        from app.analyzer.client import LlmCallResult

        return result_doc, LlmCallResult(
            response_json=result_doc.model_dump(), tokens_in=500, tokens_out=100, cost_usd=Decimal("0.01")
        )

    monkeypatch.setattr("app.tasks.jobs.synthesize_module_doc", _fake_synthesize)
    monkeypatch.setattr("app.tasks.jobs.embed_text", _fake_embed_text([]))

    module = await seed_corpus(db_session, str(demo_store_path))

    assert module.state == "up_to_date"
    assert module.repo_root == str(demo_store_path.resolve())


@pytest.mark.asyncio
async def test_seed_corpus_wipes_any_previously_seeded_module_first(
    demo_store_path: Path, demo_module_path: Path, db_session, monkeypatch
):
    """"Wipe every module" is destructive by design (only safe against a
    disposable DB) — confirm a module from an unrelated prior run doesn't
    survive a fresh seed_corpus() call.
    """
    leftover = Module(
        repo_root=f"/tmp/leftover-{uuid.uuid4().hex[:8]}", name="LeftoverModule", path=".",
        source_type="standalone", state="up_to_date", current_hash="x", last_scanned_at=datetime.now(UTC),
    )
    db_session.add(leftover)
    await db_session.commit()

    async def _never_exceeded(session):
        return False

    monkeypatch.setattr("app.tasks.jobs.is_budget_exceeded", _never_exceeded)
    monkeypatch.setattr("app.tasks.jobs.summarize_file", fake_summarize_file())

    async def _fake_synthesize(facts, known_sources, known_config_paths, **kwargs):
        from app.analyzer.client import LlmCallResult

        return _fake_doc(), LlmCallResult(
            response_json=_fake_doc().model_dump(), tokens_in=10, tokens_out=5, cost_usd=Decimal("0.001")
        )

    monkeypatch.setattr("app.tasks.jobs.synthesize_module_doc", _fake_synthesize)
    monkeypatch.setattr("app.tasks.jobs.embed_text", _fake_embed_text([]))

    await seed_corpus(db_session, str(demo_module_path))

    assert await db_session.scalar(select(Module).where(Module.id == leftover.id)) is None


@pytest.mark.asyncio
async def test_seed_corpus_raises_when_scan_repository_finds_no_module(tmp_path: Path, db_session):
    with pytest.raises(RuntimeError, match="did not create a module"):
        await seed_corpus(db_session, str(tmp_path))


@pytest.mark.asyncio
async def test_seed_corpus_raises_when_the_pipeline_does_not_reach_up_to_date(
    demo_module_path: Path, db_session, monkeypatch
):
    """A real, non-LLM failure mode: the budget is exhausted before analysis can
    even start, leaving the module stuck at paused_budget rather than
    up_to_date.
    """
    async def _always_exceeded(session):
        return True

    monkeypatch.setattr("app.tasks.jobs.is_budget_exceeded", _always_exceeded)

    # AnalysisCache is keyed purely by content hash, globally, not per-module —
    # an earlier test's real analysis of this exact fixture content (e.g. demo_store_path,
    # which contains these same files) would otherwise cache-hit and skip the budget
    # check entirely, letting this test's module reach up_to_date regardless.
    from app.models import AnalysisCache

    await db_session.execute(delete(AnalysisCache).where(AnalysisCache.kind == "file_summary"))
    await db_session.commit()

    with pytest.raises(RuntimeError, match="pipeline did not complete"):
        await seed_corpus(db_session, str(demo_module_path))


@pytest.mark.asyncio
async def test_relevant_chunk_ids_matches_module_sentinel_and_relative_paths(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = Module(
        repo_root=f"/tmp/runner-test-{suffix}", name=f"RunnerTestModule_{suffix}", path=".",
        source_type="standalone", state="up_to_date", current_hash="x", last_scanned_at=datetime.now(UTC),
    )
    db_session.add(module)
    await db_session.flush()

    module_chunk = Chunk(
        module_id=module.id, chunk_type="module", relative_path=None,
        content_hash=f"mod-{suffix}", text="module chunk", embedding=[0.0] * 1536,
    )
    file_chunk = Chunk(
        module_id=module.id, chunk_type="file", relative_path="Foo.php",
        content_hash=f"file-{suffix}", text="file chunk", embedding=[0.0] * 1536,
    )
    other_chunk = Chunk(
        module_id=module.id, chunk_type="file", relative_path="Bar.php",
        content_hash=f"other-{suffix}", text="other chunk", embedding=[0.0] * 1536,
    )
    db_session.add_all([module_chunk, file_chunk, other_chunk])
    await db_session.commit()

    ids = await _relevant_chunk_ids(db_session, module.id, frozenset({MODULE_SENTINEL, "Foo.php"}))
    assert ids == {module_chunk.id, file_chunk.id}

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


def test_resolve_kwargs_substitutes_the_module_id_placeholder():
    resolved = _resolve_kwargs({"module_id": MODULE_ID_PLACEHOLDER, "relative_path": "Foo.php"}, 42)
    assert resolved == {"module_id": 42, "relative_path": "Foo.php"}


@pytest.mark.asyncio
async def test_run_enumeration_eval_runs_the_real_tool_and_checks_the_predicate(demo_store_path, db_session):
    from app.evaluation.runner import run_enumeration_eval

    module = await scan_demo_store(demo_store_path, db_session)
    questions = [
        EnumerationQuestion(
            id="e1", query="does this module exist?", tool="get_module",
            tool_kwargs={"module_id": MODULE_ID_PLACEHOLDER}, expected=lambda r: r.get("found") is True,
        )
    ]

    results = await run_enumeration_eval(db_session, questions, module)

    assert results == [QuestionResult(id="e1", query="does this module exist?", passed=True, detail=results[0].detail)]
    assert results[0].passed is True


@pytest.mark.asyncio
async def test_run_negative_eval_tool_mode(demo_store_path, db_session):
    from app.evaluation.runner import run_negative_eval

    module = await scan_demo_store(demo_store_path, db_session)
    questions = [
        NegativeQuestion(
            id="n1", query="does a nonexistent module exist?", mode="tool", tool="get_module",
            tool_kwargs={"module_id": -1}, expected_empty=lambda r: r.get("found") is False,
        )
    ]

    results = await run_negative_eval(db_session, questions, module)

    assert results[0].passed is True


@pytest.mark.asyncio
async def test_run_negative_eval_agent_mode(demo_store_path, db_session, monkeypatch):
    from app.evaluation.runner import run_negative_eval

    module = await scan_demo_store(demo_store_path, db_session)

    async def _fake_run_agent(session, messages, audience):
        yield {"event": "token", "text": "I could not find anything about that."}
        yield {"event": "done", "tokens_in": 1, "tokens_out": 1, "cost_usd": "0"}

    monkeypatch.setattr("app.evaluation.runner.run_agent", _fake_run_agent)

    questions = [
        NegativeQuestion(
            id="n2", query="does this module integrate with a payment gateway?", mode="agent",
            expected_answer=lambda text: "could not find" in text.lower(),
        )
    ]

    results = await run_negative_eval(db_session, questions, module)

    assert results[0].passed is True
    assert "could not find" in results[0].detail.lower()


@pytest.mark.asyncio
async def test_run_faithfulness_eval_records_a_grounded_verdict(db_session, monkeypatch):
    async def _fake_run_agent(session, messages, audience):
        yield {"event": "sources", "sources": [{"module_id": 1, "module_name": "M", "relative_path": None}]}
        yield {"event": "token", "text": "It sends SMS via Twilio."}
        yield {"event": "done", "tokens_in": 1, "tokens_out": 1, "cost_usd": "0"}

    async def _fake_judge(session, question, answer, sources, *, model, api_key, api_base=None):
        assert answer == "It sends SMS via Twilio."
        assert sources == [{"module_id": 1, "module_name": "M", "relative_path": None}]
        from app.evaluation.faithfulness import FaithfulnessVerdict

        return FaithfulnessVerdict(grounded=True, unsupported_claims=[], reasoning="matches")

    monkeypatch.setattr("app.evaluation.runner.run_agent", _fake_run_agent)
    monkeypatch.setattr("app.evaluation.runner.judge_faithfulness", _fake_judge)

    questions = [RetrievalQuestion(id="f1", query="does it send SMS?", category="semantic", relevant_relative_paths=frozenset())]

    results = await run_faithfulness_eval(db_session, questions, model="m", api_key="k")

    assert results[0].outcome == "grounded"


@pytest.mark.asyncio
async def test_run_faithfulness_eval_records_an_unsupported_verdict(db_session, monkeypatch):
    async def _fake_run_agent(session, messages, audience):
        yield {"event": "sources", "sources": []}
        yield {"event": "token", "text": "It also caches with Redis."}
        yield {"event": "done", "tokens_in": 1, "tokens_out": 1, "cost_usd": "0"}

    async def _fake_judge(session, question, answer, sources, *, model, api_key, api_base=None):
        from app.evaluation.faithfulness import FaithfulnessVerdict

        return FaithfulnessVerdict(grounded=False, unsupported_claims=["Redis claim has no source"], reasoning="no")

    monkeypatch.setattr("app.evaluation.runner.run_agent", _fake_run_agent)
    monkeypatch.setattr("app.evaluation.runner.judge_faithfulness", _fake_judge)

    questions = [RetrievalQuestion(id="f2", query="q", category="semantic", relevant_relative_paths=frozenset())]

    results = await run_faithfulness_eval(db_session, questions, model="m", api_key="k")

    assert results[0].outcome == "unsupported"
    assert results[0].unsupported_claims == ["Redis claim has no source"]


@pytest.mark.asyncio
async def test_run_faithfulness_eval_records_agent_error_on_budget_exceeded(db_session, monkeypatch):
    async def _fake_run_agent(session, messages, audience):
        yield {"event": "error", "detail": "Monthly LLM budget exceeded — cannot answer right now."}
        yield {"event": "done", "tokens_in": 0, "tokens_out": 0, "cost_usd": "0"}

    judge_called = False

    async def _fake_judge(*args, **kwargs):
        nonlocal judge_called
        judge_called = True

    monkeypatch.setattr("app.evaluation.runner.run_agent", _fake_run_agent)
    monkeypatch.setattr("app.evaluation.runner.judge_faithfulness", _fake_judge)

    questions = [RetrievalQuestion(id="f3", query="q", category="semantic", relevant_relative_paths=frozenset())]

    results = await run_faithfulness_eval(db_session, questions, model="m", api_key="k")

    assert results[0].outcome == "agent_error"
    assert "budget" in results[0].reasoning.lower()
    assert judge_called is False


@pytest.mark.asyncio
async def test_run_faithfulness_eval_records_agent_error_on_an_empty_answer(db_session, monkeypatch):
    async def _fake_run_agent(session, messages, audience):
        yield {"event": "sources", "sources": []}
        yield {"event": "done", "tokens_in": 0, "tokens_out": 0, "cost_usd": "0"}

    monkeypatch.setattr("app.evaluation.runner.run_agent", _fake_run_agent)

    questions = [RetrievalQuestion(id="f4", query="q", category="semantic", relevant_relative_paths=frozenset())]

    results = await run_faithfulness_eval(db_session, questions, model="m", api_key="k")

    assert results[0].outcome == "agent_error"
    assert "empty answer" in results[0].reasoning.lower()


@pytest.mark.asyncio
async def test_run_faithfulness_eval_records_judge_error_without_aborting(db_session, monkeypatch):
    async def _fake_run_agent(session, messages, audience):
        yield {"event": "sources", "sources": []}
        yield {"event": "token", "text": "an answer"}
        yield {"event": "done", "tokens_in": 1, "tokens_out": 1, "cost_usd": "0"}

    async def _fake_judge(*args, **kwargs):
        raise RuntimeError("provider rejected the request")

    monkeypatch.setattr("app.evaluation.runner.run_agent", _fake_run_agent)
    monkeypatch.setattr("app.evaluation.runner.judge_faithfulness", _fake_judge)

    questions = [
        RetrievalQuestion(id="f5", query="q1", category="semantic", relevant_relative_paths=frozenset()),
        RetrievalQuestion(id="f6", query="q2", category="semantic", relevant_relative_paths=frozenset()),
    ]

    results = await run_faithfulness_eval(db_session, questions, model="m", api_key="k")

    # One bad judge call doesn't abort the whole eval run -- both questions
    # get a result, both correctly marked as a judge error.
    assert [r.outcome for r in results] == ["judge_error", "judge_error"]
    assert "provider rejected" in results[0].reasoning


@pytest.mark.asyncio
async def test_run_retrieval_eval_raises_when_no_chunk_matches(demo_store_path, db_session):
    from app.evaluation.runner import run_retrieval_eval

    module = await scan_demo_store(demo_store_path, db_session)
    questions = [
        RetrievalQuestion(
            id="r1", query="anything", category="semantic",
            relevant_relative_paths=frozenset({"NoSuchFile.php"}),
        )
    ]

    with pytest.raises(RuntimeError, match="no chunk matched"):
        await run_retrieval_eval(db_session, questions, module)


@pytest.mark.asyncio
async def test_run_retrieval_eval_scores_vector_keyword_and_hybrid_for_a_real_match(
    demo_store_path, db_session, monkeypatch
):
    from app.evaluation.runner import run_retrieval_eval

    module = await scan_demo_store(demo_store_path, db_session)
    chunk = Chunk(
        module_id=module.id, chunk_type="module", relative_path=None,
        content_hash=f"runner-retrieval-{uuid.uuid4().hex[:8]}", text="irrelevant", embedding=[0.0] * 1536,
    )
    db_session.add(chunk)
    await db_session.commit()

    async def _fake_embed(query, **kwargs):
        return [0.0] * 1536

    monkeypatch.setattr("app.search.hybrid.embed_query_text", _fake_embed)
    monkeypatch.setattr("app.evaluation.isolated_retrieval.embed_query_text", _fake_embed)

    questions = [
        RetrievalQuestion(
            id="r1", query="anything", category="semantic",
            relevant_relative_paths=frozenset({MODULE_SENTINEL}),
        )
    ]

    metrics = await run_retrieval_eval(db_session, questions, module)

    assert set(metrics) == {"vector", "keyword", "hybrid"}
    for mode_metrics in metrics.values():
        assert "mrr" in mode_metrics


def test_eval_report_to_dict_and_markdown_table():
    metrics = {mode: {f"recall@{k}": 1.0 for k in (1, 3, 5, 10)} | {"mrr": 1.0} for mode in ("vector", "keyword", "hybrid")}
    report = EvalReport(
        generated_at="2026-01-01T00:00:00+00:00",
        corpus="Vendor_Module",
        retrieval_metrics=metrics,
        enumeration_results=[QuestionResult(id="e1", query="q", passed=True, detail="d")],
        negative_results=[
            QuestionResult(id="n1", query="q", passed=True, detail="d"),
            QuestionResult(id="n2", query="q", passed=False, detail="d"),
        ],
    )

    as_dict = report.to_dict()
    assert as_dict["corpus"] == "Vendor_Module"
    assert as_dict["enumeration_results"] == [{"id": "e1", "query": "q", "passed": True, "detail": "d"}]

    table = report.to_markdown_table()
    assert "Enumeration: 1/1 passed." in table
    assert 'Negative/"not found": 1/2 passed.' in table
    assert "Faithfulness" not in table  # no faithfulness_results -> no line at all


def test_eval_report_to_markdown_table_includes_faithfulness_when_present():
    from app.evaluation.runner import FaithfulnessResult

    metrics = {mode: {f"recall@{k}": 1.0 for k in (1, 3, 5, 10)} | {"mrr": 1.0} for mode in ("vector", "keyword", "hybrid")}
    report = EvalReport(
        generated_at="2026-01-01T00:00:00+00:00",
        corpus="Vendor_Module",
        retrieval_metrics=metrics,
        enumeration_results=[],
        negative_results=[],
        faithfulness_results=[
            FaithfulnessResult(id="f1", query="q1", outcome="grounded", reasoning="ok"),
            FaithfulnessResult(id="f2", query="q2", outcome="unsupported", unsupported_claims=["x"], reasoning="no"),
            FaithfulnessResult(id="f3", query="q3", outcome="judge_error", reasoning="boom"),
        ],
    )

    as_dict = report.to_dict()
    assert as_dict["faithfulness_results"][0] == {
        "id": "f1", "query": "q1", "outcome": "grounded", "unsupported_claims": [], "reasoning": "ok",
    }

    table = report.to_markdown_table()
    assert "Faithfulness (LLM-judged, grounded in cited sources): 1/2 judged answers." in table
    assert "1 agent/judge error(s)" in table
