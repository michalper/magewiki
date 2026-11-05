"""Drives the real evaluation: seeds a known corpus by running the exact
production scan -> analyze -> synthesize -> embed pipeline against the
Ordo_Automation fixture, then scores retrieval/enumeration/negative questions
against it. See backend/app/evaluation/dataset.py for the question set and
backend/app/evaluation/metrics.py for recall@k/MRR.
"""

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import run_agent
from app.agent.tools import TOOL_FUNCTIONS
from app.evaluation.dataset import (
    MODULE_ID_PLACEHOLDER,
    MODULE_SENTINEL,
    EnumerationQuestion,
    NegativeQuestion,
    RetrievalQuestion,
)
from app.evaluation.isolated_retrieval import keyword_only_search, vector_only_search
from app.evaluation.metrics import aggregate
from app.models import Chunk, FileHash, Module
from app.scanner.orchestrator import scan_repository
from app.search.hybrid import hybrid_search
from app.tasks.jobs import analyze_file, embed_chunks, synthesize_module


async def seed_corpus(session: AsyncSession, repo_root: str) -> Module:
    """Wipe every module, then build the exact given fixture through the real
    production pipeline (not a shortcut). Destructive: only run against a
    disposable dev database.
    """
    await session.execute(delete(Module))
    await session.commit()

    await scan_repository(repo_root, session)

    resolved_root = str(Path(repo_root).resolve())
    module = await session.scalar(select(Module).where(Module.repo_root == resolved_root))
    if module is None:
        raise RuntimeError(f"scan_repository did not create a module for {repo_root!r}")

    pending = (
        await session.scalars(
            select(FileHash).where(FileHash.module_id == module.id, FileHash.analyzed.is_(False))
        )
    ).all()
    for fh in pending:
        await analyze_file(None, module.id, fh.relative_path, fh.content_hash, module.current_hash)

    await session.refresh(module)
    # analyze_file/synthesize_module hand off the next pipeline step via ARQ
    # enqueue_job — with no worker running here, drive the remaining steps
    # in-process ourselves, same pattern as
    # tests/search/test_hybrid_search_embeddings.py.
    if module.state == "analyzing":
        await synthesize_module(None, module.id, module.current_hash)
        await session.refresh(module)

    if module.state == "embedding":
        await embed_chunks(None, module.id, module.current_hash)
        await session.refresh(module)

    if module.state != "up_to_date":
        raise RuntimeError(f"pipeline did not complete: state={module.state!r}, last_error={module.last_error!r}")

    return module


async def _relevant_chunk_ids(session: AsyncSession, module_id: int, relative_paths: frozenset[str]) -> set[int]:
    chunks = (await session.scalars(select(Chunk).where(Chunk.module_id == module_id))).all()
    return {
        c.id
        for c in chunks
        if (c.chunk_type == "module" and MODULE_SENTINEL in relative_paths)
        or (c.relative_path in relative_paths)
    }


@dataclass
class QuestionResult:
    id: str
    query: str
    passed: bool
    detail: str = ""


async def run_retrieval_eval(
    session: AsyncSession, questions: list[RetrievalQuestion], module: Module
) -> dict[str, dict[str, float]]:
    per_mode: dict[str, list[tuple[Sequence[int], set[int]]]] = {"vector": [], "keyword": [], "hybrid": []}
    for q in questions:
        relevant = await _relevant_chunk_ids(session, module.id, q.relevant_relative_paths)
        if not relevant:
            raise RuntimeError(f"question {q.id!r}: no chunk matched {q.relevant_relative_paths!r}")

        vector_results = await vector_only_search(session, q.query, limit=10)
        keyword_results = await keyword_only_search(session, q.query, limit=10)
        hybrid_results = await hybrid_search(session, q.query, limit=10)

        per_mode["vector"].append(([r.chunk_id for r in vector_results], relevant))
        per_mode["keyword"].append(([r.chunk_id for r in keyword_results], relevant))
        per_mode["hybrid"].append(([r.chunk_id for r in hybrid_results], relevant))

    return {mode: aggregate(rows) for mode, rows in per_mode.items()}


def _resolve_kwargs(tool_kwargs: dict, module_id: int) -> dict:
    return {k: (module_id if v == MODULE_ID_PLACEHOLDER else v) for k, v in tool_kwargs.items()}


async def run_enumeration_eval(
    session: AsyncSession, questions: list[EnumerationQuestion], module: Module
) -> list[QuestionResult]:
    results = []
    for q in questions:
        kwargs = _resolve_kwargs(q.tool_kwargs, module.id)
        tool_result = await TOOL_FUNCTIONS[q.tool](session, **kwargs)
        passed = q.expected(tool_result)
        results.append(QuestionResult(id=q.id, query=q.query, passed=passed, detail=json.dumps(tool_result)[:500]))
    return results


async def run_negative_eval(
    session: AsyncSession, questions: list[NegativeQuestion], module: Module
) -> list[QuestionResult]:
    results = []
    for q in questions:
        if q.mode == "tool":
            kwargs = _resolve_kwargs(q.tool_kwargs, module.id)
            tool_result = await TOOL_FUNCTIONS[q.tool](session, **kwargs)
            passed = q.expected_empty(tool_result)
            results.append(
                QuestionResult(id=q.id, query=q.query, passed=passed, detail=json.dumps(tool_result)[:500])
            )
        else:
            final_text = ""
            async for event in run_agent(session, [{"role": "user", "content": q.query}], "dev"):
                if event.get("event") == "token":
                    final_text += event.get("text", "")
            passed = q.expected_answer(final_text)
            results.append(QuestionResult(id=q.id, query=q.query, passed=passed, detail=final_text[:500]))
    return results


@dataclass
class EvalReport:
    generated_at: str
    corpus: str
    retrieval_metrics: dict[str, dict[str, float]]
    enumeration_results: list[QuestionResult]
    negative_results: list[QuestionResult]

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "corpus": self.corpus,
            "retrieval_metrics": self.retrieval_metrics,
            "enumeration_results": [asdict(r) for r in self.enumeration_results],
            "negative_results": [asdict(r) for r in self.negative_results],
        }

    def to_markdown_table(self) -> str:
        ks = (1, 3, 5, 10)
        header = "| Mode | " + " | ".join(f"recall@{k}" for k in ks) + " | MRR |"
        sep = "|---" * (len(ks) + 2) + "|"
        label_by_mode = {"vector": "Vector-only", "keyword": "FTS-only", "hybrid": "Hybrid (RRF)"}
        rows = []
        for mode in ("vector", "keyword", "hybrid"):
            m = self.retrieval_metrics[mode]
            cells = " | ".join(f"{m[f'recall@{k}']:.2f}" for k in ks)
            rows.append(f"| {label_by_mode[mode]} | {cells} | {m['mrr']:.2f} |")

        enum_passed = sum(r.passed for r in self.enumeration_results)
        neg_passed = sum(r.passed for r in self.negative_results)

        lines = [
            header,
            sep,
            *rows,
            "",
            f"Enumeration: {enum_passed}/{len(self.enumeration_results)} passed.",
            f"Negative/\"not found\": {neg_passed}/{len(self.negative_results)} passed.",
        ]
        return "\n".join(lines)
