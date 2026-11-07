from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import RuntimeLlmConfig

_OLLAMA_PREFIXES = ("ollama/", "ollama_chat/")


@dataclass
class ResolvedModel:
    model: str
    api_key: str | None
    api_base: str | None


async def resolve_llm_config(session: AsyncSession) -> ResolvedModel:
    row = await session.get(RuntimeLlmConfig, 1)
    model = (row.llm_model if row else None) or settings.llm_model
    api_base = (row.llm_api_base if row else None) or (
        settings.ollama_base_url if model.startswith(_OLLAMA_PREFIXES) else None
    )
    return ResolvedModel(model=model, api_key=(row.llm_api_key if row else None), api_base=api_base or None)


async def resolve_synthesis_llm_config(session: AsyncSession) -> ResolvedModel:
    """Same provider credentials as resolve_llm_config (same BYOK key/base) — only
    the model name differs, when settings.synthesis_model opts into a stronger model
    for the module-synthesis step specifically. See config.py's synthesis_model.
    """
    base = await resolve_llm_config(session)
    return ResolvedModel(model=settings.synthesis_model or base.model, api_key=base.api_key, api_base=base.api_base)


async def resolve_embedding_config(session: AsyncSession) -> ResolvedModel:
    row = await session.get(RuntimeLlmConfig, 1)
    model = (row.embedding_model if row else None) or settings.embedding_model
    api_base = (row.embedding_api_base if row else None) or (
        settings.ollama_base_url if model.startswith(_OLLAMA_PREFIXES) else None
    )
    return ResolvedModel(model=model, api_key=(row.embedding_api_key if row else None), api_base=api_base or None)
