from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.analyzer.budget import is_budget_exceeded
from app.analyzer.client import summarize_file, synthesize_module_doc
from app.analyzer.facts import gather_module_facts, known_sources
from app.analyzer.prompts import FILE_SUMMARY_PROMPT_VERSION, MODULE_SYNTHESIS_PROMPT_VERSION
from app.analyzer.tags import derive_parser_tags, filter_tags, merge_tags
from app.config import settings
from app.db import async_session_factory
from app.models import AnalysisCache, FileAnalysis, FileHash, Module, ModuleDocument
from app.tasks.queue import get_arq_pool


async def _get_or_create_cache_entry(session, content_hash: str, prompt_version: str, kind: str, result) -> int:
    insert_stmt = (
        pg_insert(AnalysisCache)
        .values(
            content_hash=content_hash,
            model=settings.llm_model,
            prompt_version=prompt_version,
            kind=kind,
            response=result.response_json,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )
        .on_conflict_do_nothing(index_elements=["content_hash", "model", "prompt_version", "kind"])
        .returning(AnalysisCache.id)
    )
    inserted = (await session.execute(insert_stmt)).first()
    if inserted is not None:
        return inserted.id

    existing_id = await session.scalar(
        select(AnalysisCache.id).where(
            AnalysisCache.content_hash == content_hash,
            AnalysisCache.model == settings.llm_model,
            AnalysisCache.prompt_version == prompt_version,
            AnalysisCache.kind == kind,
        )
    )
    return existing_id


async def _lookup_cache(session, content_hash: str, prompt_version: str, kind: str) -> AnalysisCache | None:
    return await session.scalar(
        select(AnalysisCache).where(
            AnalysisCache.content_hash == content_hash,
            AnalysisCache.model == settings.llm_model,
            AnalysisCache.prompt_version == prompt_version,
            AnalysisCache.kind == kind,
        )
    )


async def analyze_file(
    ctx: dict,
    module_id: int,
    relative_path: str,
    content_hash: str,
    module_current_hash: str,
) -> None:
    """Summarize one changed/added file with the LLM (cached by content hash), then
    mark it analyzed and, once the module's last outstanding file is done, enqueue
    synthesize_module. See CLAUDE.md "Scan, cron, and cost control" for the design.

    Uses the session's default autobegin (no explicit session.begin() blocks) and
    commits at natural stopping points — the same transaction style as
    app/scanner/orchestrator.py.
    """
    try:
        async with async_session_factory() as session:
            module = await session.get(Module, module_id)
            if module is None or module.current_hash != module_current_hash:
                return  # stale job from a superseded scan generation

            cached = await _lookup_cache(session, content_hash, FILE_SUMMARY_PROMPT_VERSION, "file_summary")

            if cached is None:
                if await is_budget_exceeded(session):
                    await session.execute(
                        update(Module)
                        .where(Module.id == module_id, Module.current_hash == module_current_hash)
                        .values(state="paused_budget")
                    )
                    await session.commit()
                    return

                file_path = Path(module.repo_root) / module.path / relative_path
                content = file_path.read_text(encoding="utf-8", errors="replace")
                _summary, result = await summarize_file(relative_path, content)

                cache_id = await _get_or_create_cache_entry(
                    session, content_hash, FILE_SUMMARY_PROMPT_VERSION, "file_summary", result
                )
            else:
                cache_id = cached.id

            fa_stmt = (
                pg_insert(FileAnalysis)
                .values(module_id=module_id, relative_path=relative_path, content_hash=content_hash, cache_id=cache_id)
                .on_conflict_do_update(
                    index_elements=["module_id", "relative_path"],
                    set_={"content_hash": content_hash, "cache_id": cache_id},
                )
            )
            await session.execute(fa_stmt)

            marked = await session.execute(
                update(FileHash)
                .where(
                    FileHash.module_id == module_id,
                    FileHash.relative_path == relative_path,
                    FileHash.content_hash == content_hash,
                    FileHash.analyzed.is_(False),
                )
                .values(analyzed=True)
                .returning(FileHash.id)
            )
            if marked.first() is None:
                await session.commit()
                return  # stale retry or superseded scan — nothing more to do

            decremented = await session.execute(
                update(Module)
                .where(Module.id == module_id, Module.current_hash == module_current_hash)
                .values(pending_file_count=Module.pending_file_count - 1, state="analyzing")
                .returning(Module.pending_file_count)
            )
            row = decremented.first()
            await session.commit()

            if row is not None and row.pending_file_count == 0:
                pool = await get_arq_pool()
                await pool.enqueue_job(
                    "synthesize_module",
                    module_id,
                    module_current_hash,
                    _job_id=f"synthesize:{module_id}:{module_current_hash}",
                )
    except Exception as exc:  # noqa: BLE001 - recorded on the module, then re-raised for ARQ's retry
        async with async_session_factory() as session:
            await session.execute(
                update(Module)
                .where(Module.id == module_id)
                .values(state="failed", retry_count=Module.retry_count + 1, last_error=str(exc))
            )
            await session.commit()
        raise


async def synthesize_module(ctx: dict, module_id: int, module_current_hash: str) -> None:
    """Map-reduce over a module's file summaries + parser facts into the module-level
    JSON doc, once every changed/added file has been analyzed.
    """
    try:
        async with async_session_factory() as session:
            module = await session.get(Module, module_id)
            if module is None or module.current_hash != module_current_hash:
                return  # stale job from a superseded scan generation

            cached = await _lookup_cache(
                session, module_current_hash, MODULE_SYNTHESIS_PROMPT_VERSION, "module_synthesis"
            )

            if cached is None:
                if await is_budget_exceeded(session):
                    await session.execute(
                        update(Module)
                        .where(Module.id == module_id, Module.current_hash == module_current_hash)
                        .values(state="paused_budget")
                    )
                    await session.commit()
                    return

                facts = await gather_module_facts(session, module_id)
                sources = known_sources(facts)
                doc, result = await synthesize_module_doc(facts, sources)

                parser_tags = derive_parser_tags(facts.dependencies)
                ai_tags, rejected = filter_tags(doc.tags)
                doc.tags = merge_tags(parser_tags, ai_tags)
                doc.rejected_tags = rejected
                response_json = doc.model_dump(mode="json")
                result.response_json = response_json

                cache_id = await _get_or_create_cache_entry(
                    session, module_current_hash, MODULE_SYNTHESIS_PROMPT_VERSION, "module_synthesis", result
                )
            else:
                cache_id = cached.id
                response_json = cached.response

            doc_stmt = (
                pg_insert(ModuleDocument)
                .values(
                    module_id=module_id,
                    content_hash=module_current_hash,
                    model=settings.llm_model,
                    prompt_version=MODULE_SYNTHESIS_PROMPT_VERSION,
                    cache_id=cache_id,
                    doc=response_json,
                )
                .on_conflict_do_update(
                    index_elements=["module_id"],
                    set_={
                        "content_hash": module_current_hash,
                        "model": settings.llm_model,
                        "prompt_version": MODULE_SYNTHESIS_PROMPT_VERSION,
                        "cache_id": cache_id,
                        "doc": response_json,
                    },
                )
            )
            await session.execute(doc_stmt)

            await session.execute(
                update(Module)
                .where(Module.id == module_id, Module.current_hash == module_current_hash)
                .values(state="up_to_date", analyzed_hash=module_current_hash, last_error=None, retry_count=0)
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        async with async_session_factory() as session:
            await session.execute(
                update(Module)
                .where(Module.id == module_id)
                .values(state="failed", retry_count=Module.retry_count + 1, last_error=str(exc))
            )
            await session.commit()
        raise
