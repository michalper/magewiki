import json
import logging
import uuid
from decimal import Decimal

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.budget import is_budget_exceeded
from app.analyzer.pricing import compute_cost_usd
from app.analyzer.prompts import RERANK_PROMPT_VERSION, build_rerank_prompt
from app.models import AnalysisCache
from app.observability import LLM_CALL_COST_USD, LLM_CALLS_TOTAL
from app.runtime_config import resolve_llm_config
from app.search.hybrid import SearchResult

logger = logging.getLogger(__name__)

_RERANK_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked_chunk_ids": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Every candidate chunk id, ordered most to least relevant.",
        }
    },
    "required": ["ranked_chunk_ids"],
}


async def rerank_results(session: AsyncSession, query: str, results: list[SearchResult], *, top_k: int) -> list[SearchResult]:
    """Best-effort: a reranker that silently changes which sources an answer
    cites is worse than one that's occasionally absent, so any failure here
    (budget, a provider error, a malformed response) falls back to the
    hybrid retriever's own order rather than raising -- the caller always
    gets a usable top_k slice either way.
    """
    if not results:
        return results[:top_k]
    if await is_budget_exceeded(session):
        return results[:top_k]

    config = await resolve_llm_config(session)
    by_id = {r.chunk_id: r for r in results}
    prompt = build_rerank_prompt(query, [(r.chunk_id, r.text) for r in results])

    try:
        response = await litellm.acompletion(
            model=config.model,
            api_key=config.api_key,
            api_base=config.api_base,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"type": "function", "function": {"name": "submit_ranking", "parameters": _RERANK_SCHEMA}}],
            tool_choice={"type": "function", "function": {"name": "submit_ranking"}},
            max_tokens=500,
            _skip_mcp_handler=True,
        )
        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            return results[:top_k]
        ranked_ids = json.loads(tool_calls[0].function.arguments)["ranked_chunk_ids"]
    except Exception:
        logger.warning("reranking failed, falling back to the hybrid order", exc_info=True)
        return results[:top_k]

    await _persist_rerank_cost(session, response, config.model)

    # Hallucinated ids (not in the real candidate set) are dropped; any real
    # candidate the model left out keeps its original relative order, appended
    # after everything the model did rank -- a partial ranking is still more
    # useful than discarding candidates the model simply forgot to mention.
    seen: set[int] = set()
    reordered: list[SearchResult] = []
    for chunk_id in ranked_ids:
        result = by_id.get(chunk_id)
        if result is not None and chunk_id not in seen:
            reordered.append(result)
            seen.add(chunk_id)
    for result in results:
        if result.chunk_id not in seen:
            reordered.append(result)

    return reordered[:top_k]


async def _persist_rerank_cost(session: AsyncSession, response, model: str) -> None:
    tokens_in = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens
    cost: Decimal | None = None
    try:
        raw_cost = litellm.completion_cost(completion_response=response)
        cost = Decimal(str(raw_cost)) if raw_cost else None
    except Exception:  # noqa: BLE001 - cost computation must never block search
        cost = None
    if not cost or cost <= 0:
        cost = compute_cost_usd(model, tokens_in, tokens_out)

    LLM_CALLS_TOTAL.labels(model, "rerank").inc()
    LLM_CALL_COST_USD.labels(model, "rerank").observe(float(cost))

    session.add(
        AnalysisCache(
            content_hash=f"rerank:{uuid.uuid4()}",
            model=model,
            prompt_version=RERANK_PROMPT_VERSION,
            kind="rerank",
            response={},
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )
    )
    await session.commit()
