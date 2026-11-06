"""One-time/manually-triggered real evaluation run against the Ordo_Automation
fixture. Costs real OpenAI (embeddings) + Anthropic (analysis) API spend on the
first run; cached (via AnalysisCache content-hash keys) on reruns unless fixture
content changes.

Usage: docker compose exec api python -m app.evaluation.run_eval
"""

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from app.db import async_session_factory
from app.evaluation.dataset import ENUMERATION_QUESTIONS, NEGATIVE_QUESTIONS, RETRIEVAL_QUESTIONS
from app.evaluation.runner import (
    EvalReport,
    run_enumeration_eval,
    run_negative_eval,
    run_retrieval_eval,
    seed_corpus,
)

# Same env var name as tests/conftest.py's ORDO_FIXTURE_ENV (not imported from
# the tests package to keep app/ independent of test code).
ORDO_FIXTURE_ENV = "MAGEWIKI_ORDO_FIXTURE_PATH"

REPORT_PATH = Path(__file__).parent / "report" / "eval_report.json"


async def main() -> None:
    repo_root = os.environ.get(ORDO_FIXTURE_ENV)
    if not repo_root or not os.path.isdir(repo_root):
        raise SystemExit(f"set {ORDO_FIXTURE_ENV} to a real Ordo_Automation checkout to run this eval")

    async with async_session_factory() as session:
        module = await seed_corpus(session, repo_root)
        retrieval_metrics = await run_retrieval_eval(session, RETRIEVAL_QUESTIONS, module)
        enumeration_results = await run_enumeration_eval(session, ENUMERATION_QUESTIONS, module)
        negative_results = await run_negative_eval(session, NEGATIVE_QUESTIONS, module)

    report = EvalReport(
        generated_at=datetime.now(UTC).isoformat(),
        corpus=module.name,
        retrieval_metrics=retrieval_metrics,
        enumeration_results=enumeration_results,
        negative_results=negative_results,
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report.to_dict(), indent=2))

    print(report.to_markdown_table())
    print(f"\nFull report written to {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
