import subprocess
import sys

import pytest
from sqlalchemy import select

from app.evaluation import run_ci_eval
from app.evaluation.ci_dataset import CI_SCENARIOS
from app.models import Module


@pytest.mark.asyncio
async def test_main_seeds_scores_and_reports_then_cleans_up(db_session, monkeypatch, capsys):
    """Zero-cost: embed_query_text is monkeypatched to a deterministic vector
    (same technique as test_fast_retrieval_regression.py), so this exercises the
    real seed/score/report/cleanup pipeline with no real API calls.
    """
    if run_ci_eval.REPORT_PATH.exists():
        run_ci_eval.REPORT_PATH.unlink()

    await run_ci_eval.main()

    out = capsys.readouterr().out
    assert "## RAG eval (synthetic CI corpus)" in out
    assert "Synthetic fixture" in out

    assert run_ci_eval.REPORT_PATH.exists()
    assert run_ci_eval.REPORT_PATH.read_text() == out.rstrip("\n") or out.startswith(
        run_ci_eval.REPORT_PATH.read_text()
    )

    # _cleanup() must have removed the disposable CI module again.
    modules = (
        await db_session.scalars(select(Module).where(Module.repo_root == run_ci_eval.CI_MODULE_REPO_ROOT))
    ).all()
    assert modules == []

    run_ci_eval.REPORT_PATH.unlink()


@pytest.mark.asyncio
async def test_main_removes_a_stale_ci_module_from_a_previous_run(db_session, monkeypatch):
    """_seed() deletes any pre-existing CI_MODULE_REPO_ROOT module first — a
    previous run that crashed after seeding but before _cleanup() must not leave
    the real eval looking at doubled-up data on the next run.
    """
    from datetime import UTC, datetime

    from app.models import Module as ModuleModel

    stale = ModuleModel(
        repo_root=run_ci_eval.CI_MODULE_REPO_ROOT, name="StaleCiEvalModule", path=".",
        source_type="standalone", state="up_to_date", current_hash="stale", last_scanned_at=datetime.now(UTC),
    )
    db_session.add(stale)
    await db_session.commit()

    await run_ci_eval.main()

    modules = (
        await db_session.scalars(select(Module).where(Module.repo_root == run_ci_eval.CI_MODULE_REPO_ROOT))
    ).all()
    assert modules == []

    run_ci_eval.REPORT_PATH.unlink()


def test_vector_noise_embedding_finds_the_scenarios_own_vector_noise_chunk():
    scenario = CI_SCENARIOS[0]
    expected = next(c.embedding for c in scenario.chunks if c.relative_path == "vector_noise.php")
    assert run_ci_eval._vector_noise_embedding(scenario) == expected


def test_running_the_module_as_a_script_invokes_main():
    """Covers the `if __name__ == "__main__": asyncio.run(main())` guard itself —
    main() is zero-cost (see test above), and os.environ already carries this
    session's test DATABASE_URL/REDIS_URL/scan-root overrides (set by conftest.py
    before any app import), which a subprocess inherits by default.
    """
    result = subprocess.run(
        [sys.executable, "-m", "app.evaluation.run_ci_eval"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "## RAG eval (synthetic CI corpus)" in result.stdout
