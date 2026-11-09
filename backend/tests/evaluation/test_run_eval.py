import subprocess
import sys
from datetime import UTC, datetime

import pytest

from app.evaluation import run_eval
from app.evaluation.runner import QuestionResult


class _FakeModule:
    name = "Vendor_FakeModule"


@pytest.mark.asyncio
async def test_main_exits_when_the_fixture_env_var_is_unset(monkeypatch):
    monkeypatch.delenv(run_eval.ORDO_FIXTURE_ENV, raising=False)

    with pytest.raises(SystemExit, match=run_eval.ORDO_FIXTURE_ENV):
        await run_eval.main()


@pytest.mark.asyncio
async def test_main_exits_when_the_fixture_path_is_not_a_real_directory(monkeypatch, tmp_path):
    monkeypatch.setenv(run_eval.ORDO_FIXTURE_ENV, str(tmp_path / "does-not-exist"))

    with pytest.raises(SystemExit, match=run_eval.ORDO_FIXTURE_ENV):
        await run_eval.main()


@pytest.mark.asyncio
async def test_main_seeds_scores_writes_and_prints_the_report(monkeypatch, tmp_path, capsys):
    """Zero-cost: seed_corpus and the four real-API-calling eval runners are
    monkeypatched out entirely (this script's own docstring says it costs real
    OpenAI/Anthropic spend against a real fixture — neither available in CI),
    so this exercises main()'s own orchestration/report-writing logic only.
    """
    monkeypatch.setenv(run_eval.ORDO_FIXTURE_ENV, str(tmp_path))

    async def fake_seed_corpus(session, repo_root):
        assert repo_root == str(tmp_path)
        return _FakeModule()

    async def fake_run_retrieval_eval(session, questions, module):
        empty_mode = {f"recall@{k}": 0.0 for k in (1, 3, 5, 10)} | {"mrr": 0.0}
        return {"vector": empty_mode, "keyword": empty_mode, "hybrid": {**empty_mode, "recall@1": 1.0}}

    async def fake_run_enumeration_eval(session, questions, module):
        return [QuestionResult(id="e1", query="q", passed=True, detail="")]

    async def fake_run_negative_eval(session, questions, module):
        return [QuestionResult(id="n1", query="q", passed=True, detail="")]

    async def fake_run_faithfulness_eval(session, questions, *, model, api_key, api_base=None):
        return []

    monkeypatch.setattr(run_eval, "seed_corpus", fake_seed_corpus)
    monkeypatch.setattr(run_eval, "run_retrieval_eval", fake_run_retrieval_eval)
    monkeypatch.setattr(run_eval, "run_enumeration_eval", fake_run_enumeration_eval)
    monkeypatch.setattr(run_eval, "run_negative_eval", fake_run_negative_eval)
    monkeypatch.setattr(run_eval, "run_faithfulness_eval", fake_run_faithfulness_eval)

    if run_eval.REPORT_PATH.exists():
        run_eval.REPORT_PATH.unlink()

    await run_eval.main()

    out = capsys.readouterr().out
    assert "Enumeration: 1/1 passed." in out
    assert f"Full report written to {run_eval.REPORT_PATH}" in out

    assert run_eval.REPORT_PATH.exists()
    written = run_eval.REPORT_PATH.read_text()
    assert '"corpus": "Vendor_FakeModule"' in written
    assert datetime.now(UTC).strftime("%Y-%m-%d") in written

    run_eval.REPORT_PATH.unlink()


def test_running_the_module_as_a_script_exits_cleanly_without_the_fixture():
    """Covers the `if __name__ == "__main__":` entry point itself (zero-cost: no
    fixture is set, so this hits the SystemExit guard, not the real paid eval).
    """
    import os

    env = {k: v for k, v in os.environ.items() if k != run_eval.ORDO_FIXTURE_ENV}
    result = subprocess.run(
        [sys.executable, "-m", "app.evaluation.run_eval"],
        capture_output=True, text=True, timeout=30, env=env, check=False,
    )
    assert result.returncode != 0
    assert run_eval.ORDO_FIXTURE_ENV in result.stderr
