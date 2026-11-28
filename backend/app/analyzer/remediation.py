from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.budget import is_budget_exceeded
from app.analyzer.cache import get_or_create_cache_entry, lookup_cache
from app.analyzer.client import _call_llm
from app.analyzer.embeddings import hash_text
from app.analyzer.prompts import REMEDIATION_PROMPT_VERSION, build_remediation_prompt
from app.analyzer.schemas import RemediationText
from app.runtime_config import resolve_llm_config


async def get_or_create_remediation(
    session: AsyncSession,
    module_name: str,
    check_type: str,
    severity: str,
    file_path: str | None,
    line: int | None,
    message: str,
) -> str | None:
    """A short, cached, grounded-in-this-finding-only explanation of what to
    do about it. `None` means "not available right now" (budget exceeded) --
    the caller (the route) decides what that means for its response; this
    function never raises for that case, same as rerank/query_rewrite fail
    open rather than breaking whatever called them.

    Cached by content, not by ModuleQualityFinding.id -- that id isn't
    stable across rescans (app/scanner/orchestrator.py deletes and reinserts
    every finding fresh each scan), so the real identity worth caching
    against is the finding's own (check_type, file_path, line, message)
    tuple, same reasoning as embeddings.py's hash_text(query)-keyed cache.
    """
    content_hash = hash_text(f"{check_type}|{file_path}|{line}|{message}")
    config = await resolve_llm_config(session)

    cached = await lookup_cache(session, content_hash, config.model, REMEDIATION_PROMPT_VERSION, "remediation")
    if cached is not None:
        return str(cached.response["remediation"])

    if await is_budget_exceeded(session):
        return None

    prompt = build_remediation_prompt(module_name, check_type, severity, file_path, line, message)
    doc, result = await _call_llm(
        prompt,
        RemediationText.model_json_schema(),
        config.model,
        config.api_key,
        config.api_base,
        RemediationText.model_validate,
        max_tokens=300,
    )
    await get_or_create_cache_entry(
        session, content_hash, config.model, REMEDIATION_PROMPT_VERSION, "remediation", result
    )
    await session.commit()
    return doc.remediation
