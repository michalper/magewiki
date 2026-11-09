import json
import logging
import uuid
from decimal import Decimal

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.budget import is_budget_exceeded
from app.analyzer.pricing import compute_cost_usd
from app.analyzer.prompts import QUERY_REWRITE_PROMPT_VERSION, build_query_rewrite_prompt
from app.models import AnalysisCache
from app.observability import LLM_CALL_COST_USD, LLM_CALLS_TOTAL
from app.runtime_config import resolve_llm_config

logger = logging.getLogger(__name__)

_QUERY_REWRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "rewritten_query": {
            "type": "string",
            "description": "The rewritten search query, or the original query unchanged if it's already clear.",
        }
    },
    "required": ["rewritten_query"],
}


async def rewrite_query(session: AsyncSession, query: str) -> str:
    """Best-effort: a rewrite that silently sends retrieval somewhere the
    user didn't intend is worse than no rewrite at all, so any failure here
    (budget, a provider error, a malformed response, an empty rewrite) falls
    back to the original query rather than raising -- the caller always gets
    a usable query string either way. Mirrors app/search/rerank.py's own
    fail-open shape, a different problem (reformulating the query vs.
    reordering retrieval's results) with the same cost-safety requirements.
    """
    if not query.strip():
        return query
    if await is_budget_exceeded(session):
        return query

    config = await resolve_llm_config(session)
    prompt = build_query_rewrite_prompt(query)

    try:
        response = await litellm.acompletion(
            model=config.model,
            api_key=config.api_key,
            api_base=config.api_base,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"type": "function", "function": {"name": "submit_rewrite", "parameters": _QUERY_REWRITE_SCHEMA}}],
            tool_choice={"type": "function", "function": {"name": "submit_rewrite"}},
            max_tokens=200,
            _skip_mcp_handler=True,
        )
        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            return query
        rewritten = json.loads(tool_calls[0].function.arguments)["rewritten_query"]
    except Exception:
        logger.warning("query rewriting failed, falling back to the original query", exc_info=True)
        return query

    await _persist_query_rewrite_cost(session, response, config.model)

    rewritten = rewritten.strip()
    return rewritten if rewritten else query


async def _persist_query_rewrite_cost(session: AsyncSession, response, model: str) -> None:
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

    LLM_CALLS_TOTAL.labels(model, "query_rewrite").inc()
    LLM_CALL_COST_USD.labels(model, "query_rewrite").observe(float(cost))

    session.add(
        AnalysisCache(
            content_hash=f"query_rewrite:{uuid.uuid4()}",
            model=model,
            prompt_version=QUERY_REWRITE_PROMPT_VERSION,
            kind="query_rewrite",
            response={},
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )
    )
    await session.commit()
