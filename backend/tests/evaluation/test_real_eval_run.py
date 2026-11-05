import os
from pathlib import Path

import pytest

from app.evaluation.dataset import ENUMERATION_QUESTIONS, NEGATIVE_QUESTIONS, RETRIEVAL_QUESTIONS
from app.evaluation.runner import run_enumeration_eval, run_negative_eval, run_retrieval_eval, seed_corpus
from tests.conftest import ORDO_FIXTURE_ENV, requires_ordo_fixture


@requires_ordo_fixture
@pytest.mark.slow
@pytest.mark.llm
@pytest.mark.embeddings
@pytest.mark.asyncio
async def test_real_eval_run_against_ordo_automation(db_session):
    """Regression harness for the eval code itself (not a report generator —
    see app/evaluation/run_eval.py for that). Real OpenAI embeddings + real
    Anthropic analysis/chat calls; opt in with `pytest -m "slow and llm and
    embeddings"`. Cached after the first run (AnalysisCache keyed by content
    hash), so reruns are cheap unless the fixture's content changes.
    """
    repo_root = str(Path(os.environ[ORDO_FIXTURE_ENV]).resolve())

    module = await seed_corpus(db_session, repo_root)

    retrieval_metrics = await run_retrieval_eval(db_session, RETRIEVAL_QUESTIONS, module)
    assert retrieval_metrics["hybrid"]["recall@5"] >= 0.7

    enumeration_results = await run_enumeration_eval(db_session, ENUMERATION_QUESTIONS, module)
    failed_enum = [r for r in enumeration_results if not r.passed]
    assert not failed_enum, failed_enum

    negative_results = await run_negative_eval(db_session, NEGATIVE_QUESTIONS, module)
    failed_neg = [r for r in negative_results if not r.passed]
    assert not failed_neg, failed_neg
