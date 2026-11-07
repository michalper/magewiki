"""CI-only, zero-cost "RAG eval" that runs on every PR (Phase 7b). Seeds the
synthetic scenarios from ci_dataset.py into a disposable throwaway module,
scores vector-only/keyword-only/hybrid retrieval against them, and writes a
Markdown block for a PR comment. NOT the real Ordo_Automation numbers from
Phase 7's README table — see ci_dataset.py's docstring.

Usage: docker compose exec api python -m app.evaluation.run_ci_eval
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select

from app.db import async_session_factory
from app.evaluation import isolated_retrieval
from app.evaluation.ci_dataset import CI_SCENARIOS, CiScenario
from app.evaluation.metrics import aggregate, render_markdown_table
from app.models import Chunk, Module
from app.search import hybrid

CI_MODULE_REPO_ROOT = "__magewiki_ci_eval__"
REPORT_PATH = Path(__file__).parent / "report" / "ci_eval_comment.md"


def _vector_noise_embedding(scenario: CiScenario) -> list[float]:
    chunk = next(c for c in scenario.chunks if c.relative_path == "vector_noise.php")
    return chunk.embedding


async def _seed(session) -> Module:
    await session.execute(delete(Module).where(Module.repo_root == CI_MODULE_REPO_ROOT))
    await session.commit()

    module = Module(
        repo_root=CI_MODULE_REPO_ROOT,
        name="CiEvalModule",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash="ci-eval",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()

    for scenario in CI_SCENARIOS:
        for chunk in scenario.chunks:
            session.add(
                Chunk(
                    module_id=module.id,
                    chunk_type="file",
                    relative_path=f"{scenario.id}/{chunk.relative_path}",
                    content_hash=f"{scenario.id}-{chunk.relative_path}",
                    text=chunk.text,
                    embedding=chunk.embedding,
                )
            )
    await session.commit()
    return module


async def _cleanup(session, module: Module) -> None:
    await session.execute(delete(Module).where(Module.id == module.id))
    await session.commit()


def _markdown(metrics: dict[str, dict[str, float]]) -> str:
    return "\n".join(
        [
            "## RAG eval (synthetic CI corpus)",
            "",
            render_markdown_table(metrics, ks=(1, 3)),
            "",
            ("_Synthetic fixture — not the real Ordo_Automation numbers in README._ "
             "_Proves fusion logic, not real-world quality._"),
        ]
    )


async def _run_scenario(session, scenario: CiScenario, chunks_by_path: dict[str, int]) -> dict[str, list[int]]:
    expected_vector = _vector_noise_embedding(scenario)

    async def _fake_embed(
        query: str, *, model: str, api_key: str | None, api_base: str | None = None
    ) -> list[float]:
        return expected_vector

    isolated_retrieval.embed_query_text = _fake_embed
    hybrid.embed_query_text = _fake_embed

    vector_results = await isolated_retrieval.vector_only_search(session, scenario.query, limit=50)
    keyword_results = await isolated_retrieval.keyword_only_search(session, scenario.query, limit=50)
    hybrid_results = await hybrid.hybrid_search(session, scenario.query, limit=50, topk=50)

    return {
        "vector": [r.chunk_id for r in vector_results],
        "keyword": [r.chunk_id for r in keyword_results],
        "hybrid": [r.chunk_id for r in hybrid_results],
    }


async def main() -> None:
    async with async_session_factory() as session:
        module = await _seed(session)
        try:
            # relative_path is nullable at the schema level (module-level chunks
            # don't have one), but every chunk _seed() creates here is a "file" chunk
            # with an explicit path — filtering is just making that existing
            # invariant explicit to the type checker, not changing which chunks
            # participate in these CI scenarios.
            chunks_by_path = {
                c.relative_path: c.id
                for c in (await session.scalars(select(Chunk).where(Chunk.module_id == module.id))).all()
                if c.relative_path is not None
            }

            per_mode: dict[str, list[tuple[list[int], set[int]]]] = {"vector": [], "keyword": [], "hybrid": []}
            for scenario in CI_SCENARIOS:
                relevant = {chunks_by_path[f"{scenario.id}/{scenario.relevant_relative_path}"]}
                ranked = await _run_scenario(session, scenario, chunks_by_path)
                for mode, ranked_ids in ranked.items():
                    per_mode[mode].append((ranked_ids, relevant))

            metrics = {mode: aggregate(rows, ks=(1, 3)) for mode, rows in per_mode.items()}
        finally:
            await _cleanup(session, module)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = _markdown(metrics)
    REPORT_PATH.write_text(report)
    print(report)


if __name__ == "__main__":  # pragma: no cover - entry-point guard, exercised via subprocess in tests, not instrumented
    asyncio.run(main())
