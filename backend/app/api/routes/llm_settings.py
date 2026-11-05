from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

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

    await session.commit()
    await session.refresh(row)
    return await _effective_response(session, row)
