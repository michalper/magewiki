from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.embeddings import embed_text
from app.config import settings
from app.db import get_session
from app.models import Module, RuntimeLlmConfig
from app.runtime_config import resolve_embedding_config, resolve_llm_config
from app.tasks.queue import get_arq_pool

router = APIRouter()


class LlmSettingsResponse(BaseModel):
    llm_model: str
    llm_key_configured: bool
    llm_api_base: str | None
    embedding_model: str
    embedding_key_configured: bool
    embedding_api_base: str | None
    # Set only on a PATCH that actually triggered a re-embed (None otherwise,
    # including on every GET) -- how many already up-to-date modules were just
    # queued to re-embed under the new model.
    modules_queued_for_reembed: int | None = None


class LlmSettingsUpdate(BaseModel):
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_api_base: str | None = None
    # Switching the embedding model leaves every already-embedded chunk in the
    # old model's vector space -- stale, but silently so, since nothing else
    # tracks which model produced a chunk's embedding. Re-embedding a large
    # fleet is real, billable work (not free like the parser-only checks), so
    # this is required explicitly rather than triggered automatically just
    # because embedding_model appeared in the request body.
    confirm_reembed: bool = False


async def _effective_response(session: AsyncSession, row: RuntimeLlmConfig | None) -> LlmSettingsResponse:
    llm_config = await resolve_llm_config(session)
    embedding_config = await resolve_embedding_config(session)
    return LlmSettingsResponse(
        llm_model=llm_config.model,
        llm_key_configured=bool(row and row.llm_api_key),
        llm_api_base=llm_config.api_base,
        embedding_model=embedding_config.model,
        embedding_key_configured=bool(row and row.embedding_api_key),
        embedding_api_base=embedding_config.api_base,
    )


@router.get("/settings/llm", response_model=LlmSettingsResponse)
async def get_llm_settings(session: AsyncSession = Depends(get_session)) -> LlmSettingsResponse:
    row = await session.get(RuntimeLlmConfig, 1)
    return await _effective_response(session, row)


@router.patch("/settings/llm", response_model=LlmSettingsResponse)
async def update_llm_settings(
    update: LlmSettingsUpdate, session: AsyncSession = Depends(get_session)
) -> LlmSettingsResponse:
    row = await session.get(RuntimeLlmConfig, 1)
    if row is None:
        row = RuntimeLlmConfig(id=1)
        session.add(row)

    # A field omitted from the request body leaves the stored value untouched; a
    # field explicitly sent as null resets it to the .env default. model_fields_set
    # is what distinguishes the two — update.llm_model is None in both cases.
    fields_set = update.model_fields_set

    # Security fix: every LLM/embedding call sends the stored api_key to whatever
    # api_base is currently configured (this is how the legitimate Ollama/custom-proxy
    # BYOK path already works). Without this guard, an unauthenticated caller who sent
    # ONLY {"llm_api_base": "https://attacker.example"} could redirect all future
    # traffic carrying an already-provisioned real key to a host they control, without
    # ever needing to know the key's value. Captured before any mutation below, since
    # the check is about what was ALREADY stored, not what this request is setting.
    had_llm_key = bool(row.llm_api_key)
    had_embedding_key = bool(row.embedding_api_key)
    # Must be read before any mutation below -- row is the same object
    # resolve_embedding_config() would return again later, so it reflects
    # whatever row.embedding_model is set to *at the time it's called*, not a
    # snapshot. Captured as a plain string here so the before/after comparison
    # further down is actually comparing two different points in time.
    old_embedding_model = (await resolve_embedding_config(session)).model

    if "llm_api_base" in fields_set and "llm_api_key" not in fields_set and had_llm_key:
        raise HTTPException(
            status_code=400,
            detail="changing llm_api_base for a model with an already-configured key "
            "requires providing llm_api_key again in the same request",
        )
    if (
        "embedding_api_base" in fields_set
        and "embedding_api_key" not in fields_set
        and had_embedding_key
    ):
        raise HTTPException(
            status_code=400,
            detail="changing embedding_api_base for a model with an already-configured key "
            "requires providing embedding_api_key again in the same request",
        )

    if "llm_model" in fields_set:
        row.llm_model = update.llm_model
    if "llm_api_key" in fields_set:
        row.llm_api_key = update.llm_api_key
    if "llm_api_base" in fields_set:
        row.llm_api_base = update.llm_api_base
    if "embedding_model" in fields_set:
        row.embedding_model = update.embedding_model
    if "embedding_api_key" in fields_set:
        row.embedding_api_key = update.embedding_api_key
    if "embedding_api_base" in fields_set:
        row.embedding_api_base = update.embedding_api_base

    reembed_modules: list[Module] = []
    if "embedding_model" in fields_set:
        effective = await resolve_embedding_config(session)
        # Only a genuine change to the *effective* model needs any of this --
        # re-sending today's already-effective value (a form that always
        # submits every field, or "Reset to .env default" when there was no
        # override to begin with) must be a true no-op. Previously the probe
        # below ran unconditionally whenever embedding_model was present in
        # the body at all, so a no-op Reset made a real, billable embedding
        # call and, with no embedding key configured, could 400 outright —
        # even though nothing was actually changing.
        if effective.model != old_embedding_model:
            # chunks.embedding is a fixed-dimension pgvector column (see
            # alembic/versions/0013_configurable_embedding_dimension.py) — switching to a
            # model with a different output dimension would crash the next scan's embed
            # step, not this request. Probe the real dimension now, with one tiny live
            # call, so the mismatch is caught here with an actionable error instead.
            try:
                vector, _result = await embed_text(
                    "dimension probe", model=effective.model, api_key=effective.api_key, api_base=effective.api_base
                )
            except Exception as exc:
                await session.rollback()
                raise HTTPException(
                    status_code=400, detail=f"could not verify {effective.model}'s embedding dimension: {exc}"
                ) from exc
            if len(vector) != settings.embedding_dimensions:
                await session.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"{effective.model} outputs {len(vector)}-dimensional embeddings, but this "
                        f"deployment's chunks table is configured for {settings.embedding_dimensions} "
                        "(EMBEDDING_DIMENSIONS) — changing embedding models to a different dimension "
                        "requires updating EMBEDDING_DIMENSIONS, re-running migrations, and a full re-embed."
                    ),
                )

            # Same dimension or not, a genuinely different model still leaves every
            # already-embedded chunk in the old model's vector space — silently
            # stale, since nothing tracks which model produced a chunk's embedding.
            reembed_modules = list(
                (await session.scalars(select(Module).where(Module.state == "up_to_date"))).all()
            )
            if reembed_modules and not update.confirm_reembed:
                await session.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"changing embedding_model from {old_embedding_model} to {effective.model} would leave "
                        f"{len(reembed_modules)} already-embedded module(s) in the old model's vector space until "
                        "re-embedded — resend with confirm_reembed: true to proceed (this re-runs real, billable "
                        "embedding calls for all of them)."
                    ),
                )
            for m in reembed_modules:
                m.state = "embedding"

    await session.commit()
    await session.refresh(row)

    modules_queued = None
    if reembed_modules:
        pool = await get_arq_pool()
        for m in reembed_modules:
            await pool.enqueue_job(
                "embed_chunks",
                m.id,
                m.current_hash,
                # Distinct from the job_id synthesize_module would normally use
                # for this same (module_id, current_hash) pair — the module's
                # own hash hasn't changed here, only the global embedding
                # model, so reusing that job_id risks ARQ treating this as a
                # duplicate of an already-completed job and silently skipping it.
                _job_id=f"embed:{m.id}:{m.current_hash}:reembed:{effective.model}",
            )
        modules_queued = len(reembed_modules)

    response = await _effective_response(session, row)
    response.modules_queued_for_reembed = modules_queued
    return response
