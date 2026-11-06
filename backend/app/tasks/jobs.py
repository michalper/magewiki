import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.analyzer.budget import is_budget_exceeded, pause_module_for_budget
from app.analyzer.client import summarize_file, synthesize_module_doc
from app.analyzer.embeddings import (
    build_file_chunk_text,
    build_method_chunk_text,
    build_module_chunk_text,
    embed_text,
    hash_text,
)
from app.analyzer.facts import gather_module_facts, known_sources
from app.analyzer.prompts import (
    EMBEDDING_PROMPT_VERSION,
    FILE_SUMMARY_PROMPT_VERSION,
    MODULE_SYNTHESIS_PROMPT_VERSION,
)
from app.analyzer.schemas import ModuleDoc
from app.analyzer.tags import derive_parser_tags, filter_tags, merge_tags
from app.db import async_session_factory
from app.models import (
    AnalysisCache,
    Chunk,
    FileAnalysis,
    FileHash,
    Module,
    ModuleDocument,
    PhpClass,
    PhpClassMethod,
)
from app.runtime_config import resolve_embedding_config, resolve_llm_config
from app.scanner.magento_github import (
    fetch_release_component_versions,
    fetch_release_php_constraint,
    resolve_latest_release,
)
from app.scanner.orchestrator import ScanAlreadyInProgressError, scan_repository
from app.tasks.queue import get_arq_pool

logger = logging.getLogger(__name__)


async def _get_or_create_cache_entry(
    session, content_hash: str, model: str, prompt_version: str, kind: str, result
) -> int:
    insert_stmt = (
        pg_insert(AnalysisCache)
        .values(
            content_hash=content_hash,
            model=model,
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
            AnalysisCache.model == model,
            AnalysisCache.prompt_version == prompt_version,
            AnalysisCache.kind == kind,
        )
    )
    return existing_id


async def _lookup_cache(session, content_hash: str, model: str, prompt_version: str, kind: str) -> AnalysisCache | None:
    return await session.scalar(
        select(AnalysisCache).where(
            AnalysisCache.content_hash == content_hash,
            AnalysisCache.model == model,
            AnalysisCache.prompt_version == prompt_version,
            AnalysisCache.kind == kind,
        )
    )


@asynccontextmanager
async def fail_module_on_error(module_id: int, module_current_hash: str) -> AsyncIterator[None]:
    """Shared by analyze_file/synthesize_module/embed_chunks: on any exception,
    record it onto the module and re-raise. Guarded by current_hash, same as
    every success-path update in these functions — without it, a stale job from
    a superseded scan generation that fails AFTER a newer scan has already
    finished would overwrite the new generation's healthy state with this old
    generation's failure.
    """
    try:
        yield
    except Exception as exc:
        async with async_session_factory() as session:
            await session.execute(
                update(Module)
                .where(Module.id == module_id, Module.current_hash == module_current_hash)
                .values(state="failed", retry_count=Module.retry_count + 1, last_error=str(exc))
            )
            await session.commit()
        raise


async def analyze_file(
    ctx: dict | None,
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
    async with (
        fail_module_on_error(module_id, module_current_hash),
        async_session_factory() as session,
    ):
            module = await session.get(Module, module_id)
            if module is None or module.current_hash != module_current_hash:
                return  # stale job from a superseded scan generation

            llm_config = await resolve_llm_config(session)
            cached = await _lookup_cache(
                session, content_hash, llm_config.model, FILE_SUMMARY_PROMPT_VERSION, "file_summary"
            )

            if cached is None:
                if await is_budget_exceeded(session):
                    await pause_module_for_budget(session, module_id, module_current_hash)
                    return

                file_path = Path(module.repo_root) / module.path / relative_path
                content = file_path.read_text(encoding="utf-8", errors="replace")
                _summary, result = await summarize_file(
                    relative_path,
                    content,
                    model=llm_config.model,
                    api_key=llm_config.api_key,
                    api_base=llm_config.api_base,
                )

                cache_id = await _get_or_create_cache_entry(
                    session, content_hash, llm_config.model, FILE_SUMMARY_PROMPT_VERSION, "file_summary", result
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


async def synthesize_module(ctx: dict | None, module_id: int, module_current_hash: str) -> None:
    """Map-reduce over a module's file summaries + parser facts into the module-level
    JSON doc, once every changed/added file has been analyzed. On success, hands off
    to embed_chunks (state="embedding") rather than finishing the module itself —
    the module isn't truly up to date until chunks are embedded too.
    """
    async with (
        fail_module_on_error(module_id, module_current_hash),
        async_session_factory() as session,
    ):
            module = await session.get(Module, module_id)
            if module is None or module.current_hash != module_current_hash:
                return  # stale job from a superseded scan generation

            llm_config = await resolve_llm_config(session)
            cached = await _lookup_cache(
                session, module_current_hash, llm_config.model, MODULE_SYNTHESIS_PROMPT_VERSION, "module_synthesis"
            )

            if cached is None:
                if await is_budget_exceeded(session):
                    await pause_module_for_budget(session, module_id, module_current_hash)
                    return

                facts = await gather_module_facts(session, module_id)
                sources = known_sources(facts)
                doc, result = await synthesize_module_doc(
                    facts,
                    sources,
                    model=llm_config.model,
                    api_key=llm_config.api_key,
                    api_base=llm_config.api_base,
                )

                parser_tags = derive_parser_tags(facts.dependencies)
                ai_tags, rejected = filter_tags(doc.tags)
                doc.tags = merge_tags(parser_tags, ai_tags)
                doc.rejected_tags = rejected
                response_json = doc.model_dump(mode="json")
                result.response_json = response_json

                cache_id = await _get_or_create_cache_entry(
                    session,
                    module_current_hash,
                    llm_config.model,
                    MODULE_SYNTHESIS_PROMPT_VERSION,
                    "module_synthesis",
                    result,
                )
            else:
                cache_id = cached.id
                response_json = cached.response

            doc_stmt = (
                pg_insert(ModuleDocument)
                .values(
                    module_id=module_id,
                    content_hash=module_current_hash,
                    model=llm_config.model,
                    prompt_version=MODULE_SYNTHESIS_PROMPT_VERSION,
                    cache_id=cache_id,
                    doc=response_json,
                )
                .on_conflict_do_update(
                    index_elements=["module_id"],
                    set_={
                        "content_hash": module_current_hash,
                        "model": llm_config.model,
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
                .values(state="embedding")
            )
            await session.commit()

            pool = await get_arq_pool()
            await pool.enqueue_job(
                "embed_chunks",
                module_id,
                module_current_hash,
                _job_id=f"embed:{module_id}:{module_current_hash}",
            )


async def embed_chunks(ctx: dict | None, module_id: int, module_current_hash: str) -> None:
    """Build and embed the module/file/method chunks that back hybrid search, once
    synthesis has produced a module_docs row. The final step of the pipeline —
    sets the module to up_to_date. See CLAUDE.md "Multi-level index".
    """
    async with (
        fail_module_on_error(module_id, module_current_hash),
        async_session_factory() as session,
    ):
            module = await session.get(Module, module_id)
            if module is None or module.current_hash != module_current_hash:
                return  # stale job from a superseded scan generation

            doc_row = await session.scalar(select(ModuleDocument).where(ModuleDocument.module_id == module_id))
            if doc_row is None:
                return  # synthesize_module hasn't written its doc yet — shouldn't happen, defensive no-op

            facts = await gather_module_facts(session, module_id)
            module_doc = ModuleDoc.model_validate(doc_row.doc)

            # Build the full target chunk set for this generation: (chunk_type, relative_path, method_id, text).
            specs: list[tuple[str, str | None, int | None, str]] = [
                ("module", None, None, build_module_chunk_text(module_doc))
            ]
            for fa in facts.file_analyses:
                specs.append(
                    ("file", fa.relative_path, None, build_file_chunk_text(fa.file_summary, fa.notable_behavior))
                )

            method_rows = (
                await session.execute(
                    select(PhpClassMethod, PhpClass)
                    .join(PhpClass, PhpClassMethod.class_id == PhpClass.id)
                    .where(
                        PhpClass.module_id == module_id,
                        (PhpClass.is_plugin.is_(True)) | (PhpClass.is_observer.is_(True)),
                    )
                )
            ).all()
            for method, php_class in method_rows:
                if method.start_line is None or method.end_line is None:
                    continue  # real PHP methods always have these; defensive guard for the nullable DB columns
                file_path = Path(module.repo_root) / module.path / php_class.file_path
                try:
                    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
                    source = "\n".join(lines[method.start_line - 1 : method.end_line])
                except OSError:
                    source = ""
                specs.append(
                    ("method", php_class.file_path, method.id, build_method_chunk_text(php_class.fqcn, method.name, source))
                )

            hashed_specs = [(ct, rp, mid, txt, hash_text(txt)) for ct, rp, mid, txt in specs]
            hashes = [h for *_, h in hashed_specs]

            embed_config = await resolve_embedding_config(session)
            cached_rows = (
                await session.scalars(
                    select(AnalysisCache).where(
                        AnalysisCache.content_hash.in_(hashes),
                        AnalysisCache.model == embed_config.model,
                        AnalysisCache.prompt_version == EMBEDDING_PROMPT_VERSION,
                        AnalysisCache.kind == "embedding",
                    )
                )
            ).all()
            embedding_by_hash: dict[str, list[float]] = {c.content_hash: c.response["embedding"] for c in cached_rows}

            misses = [s for s in hashed_specs if s[4] not in embedding_by_hash]
            if misses:
                # Rechecked on every iteration, not just once before the loop — a
                # module with many cache misses makes many real, billed calls here,
                # and the budget can cross its limit partway through. Aborting mid-
                # loop (rather than only before it) still returns before the
                # chunk-rebuild below, which otherwise would KeyError on the
                # embeddings this abort left un-fetched in embedding_by_hash.
                for _ct, _rp, _mid, txt, h in misses:
                    if await is_budget_exceeded(session):
                        await pause_module_for_budget(session, module_id, module_current_hash)
                        return

                    vector, result = await embed_text(
                        txt, model=embed_config.model, api_key=embed_config.api_key, api_base=embed_config.api_base
                    )
                    await _get_or_create_cache_entry(
                        session, h, embed_config.model, EMBEDDING_PROMPT_VERSION, "embedding", result
                    )
                    embedding_by_hash[h] = vector

            await session.execute(delete(Chunk).where(Chunk.module_id == module_id))
            for ct, rp, mid, txt, h in hashed_specs:
                session.add(
                    Chunk(
                        module_id=module_id,
                        chunk_type=ct,
                        relative_path=rp,
                        method_id=mid,
                        content_hash=h,
                        text=txt,
                        embedding=embedding_by_hash[h],
                    )
                )

            await session.execute(
                update(Module)
                .where(Module.id == module_id, Module.current_hash == module_current_hash)
                .values(state="up_to_date", analyzed_hash=module_current_hash, last_error=None, retry_count=0)
            )
            await session.commit()


async def scan_repository_job(ctx: dict, repo_root: str) -> None:
    """ARQ job wrapper around scan_repository — used by the HMAC webhook (and the
    nightly cron below). Opens its own session like the other jobs in this module.
    scan_repository's own Postgres advisory lock already makes two overlapping
    scans of the same repo (cron/webhook/manual) safe; ScanAlreadyInProgressError
    just means another trigger got there first, so this is a no-op, not a failure.
    """
    async with async_session_factory() as session:
        try:
            await scan_repository(repo_root, session)
        except ScanAlreadyInProgressError:
            pass


async def nightly_scan_all(ctx: dict) -> None:
    """Cron safety net (see CLAUDE.md "Scan, cron, and cost control"): re-scan every
    repo_root already known to the DB, so drift since the last scan/webhook gets
    caught even if nothing ever pinged us. One repo failing (e.g. its path no
    longer exists) must not stop the rest.
    """
    async with async_session_factory() as session:
        repo_roots = (await session.scalars(select(Module.repo_root).distinct())).all()

    for repo_root in repo_roots:
        try:
            await scan_repository_job(ctx, repo_root)
        except Exception:
            logger.exception("nightly_scan_all: scan failed for %s", repo_root)


async def refresh_magento_release_cache(ctx: dict) -> None:
    """Phase 13 cron: pre-warm the cached "latest Magento release" data daily,
    decoupled from nightly_scan_all so it stays fresh even if that job is
    failing. A new release becomes visible to every module's upgrade-
    readiness check within at most a day, via the next nightly_scan_all run
    (which recomputes every quality finding from scratch already — no
    separate recompute path needed here).
    """
    async with async_session_factory() as session:
        tag = await resolve_latest_release(session)
        if tag is None:
            logger.warning("refresh_magento_release_cache: could not resolve the latest Magento release")
            return
        await fetch_release_php_constraint(session, tag)
        await fetch_release_component_versions(session, tag)
        await session.commit()
