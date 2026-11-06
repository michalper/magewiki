from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.embeddings import embed_text
from app.config import settings
from app.db import get_session
from app.models import RuntimeLlmConfig
from app.runtime_config import resolve_embedding_config, resolve_llm_config

router = APIRouter()


class LlmSettingsResponse(BaseModel):
    llm_model: str
    llm_key_configured: bool
    llm_api_base: str | None
    embedding_model: str
    embedding_key_configured: bool
    embedding_api_base: str | None


class LlmSettingsUpdate(BaseModel):
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_api_base: str | None = None


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

    if "embedding_model" in fields_set:
        # chunks.embedding is a fixed-dimension pgvector column (see
        # alembic/versions/0013_configurable_embedding_dimension.py) — switching to a
        # model with a different output dimension would crash the next scan's embed
        # step, not this request. Probe the real dimension now, with one tiny live
        # call, so the mismatch is caught here with an actionable error instead.
        effective = await resolve_embedding_config(session)
        try:
            vector, _result = await embed_text(
                "dimension probe", model=effective.model, api_key=effective.api_key, api_base=effective.api_base
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a 400, not a crash
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

    await session.commit()
    await session.refresh(row)
    return await _effective_response(session, row)
