from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models import RuntimeLlmConfig

router = APIRouter()


class LlmSettingsResponse(BaseModel):
    llm_model: str
    llm_key_configured: bool
    embedding_model: str
    embedding_key_configured: bool


class LlmSettingsUpdate(BaseModel):
    llm_model: str | None = None
    llm_api_key: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None


def _effective_response(row: RuntimeLlmConfig | None) -> LlmSettingsResponse:
    return LlmSettingsResponse(
        llm_model=(row.llm_model if row else None) or settings.llm_model,
        llm_key_configured=bool(row and row.llm_api_key),
        embedding_model=(row.embedding_model if row else None) or settings.embedding_model,
        embedding_key_configured=bool(row and row.embedding_api_key),
    )


@router.get("/settings/llm", response_model=LlmSettingsResponse)
async def get_llm_settings(session: AsyncSession = Depends(get_session)) -> LlmSettingsResponse:
    row = await session.get(RuntimeLlmConfig, 1)
    return _effective_response(row)


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
    if "embedding_model" in fields_set:
        row.embedding_model = update.embedding_model
    if "embedding_api_key" in fields_set:
        row.embedding_api_key = update.embedding_api_key

    await session.commit()
    await session.refresh(row)
    return _effective_response(row)
