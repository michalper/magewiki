from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RuntimeLlmConfig


@dataclass
class ResolvedModel:
    model: str
    api_key: str | None


async def resolve_llm_config(session: AsyncSession) -> ResolvedModel:
    row = await session.get(RuntimeLlmConfig, 1)
    return ResolvedModel(
        model=(row.llm_model if row else None) or settings.llm_model,
        api_key=row.llm_api_key if row else None,
    )


async def resolve_embedding_config(session: AsyncSession) -> ResolvedModel:
    row = await session.get(RuntimeLlmConfig, 1)
    return ResolvedModel(
        model=(row.embedding_model if row else None) or settings.embedding_model,
        api_key=row.embedding_api_key if row else None,
    )
