import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompt import FINAL_ANSWER_INSTRUCTION, build_system_prompt
from app.agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from app.analyzer.budget import is_budget_exceeded
from app.analyzer.pricing import compute_cost_usd, resolve_llm_cost
from app.analyzer.prompts import CHAT_PROMPT_VERSION
from app.models import AnalysisCache
from app.observability import LLM_CALL_COST_USD, LLM_CALLS_TOTAL
from app.runtime_config import resolve_llm_config

MAX_TOOL_ROUNDS = 6


@dataclass
class Source:
    module_id: int
    module_name: str
    relative_path: str | None = None
    # Retrieval-debugging detail -- only ever populated for a source that came
    # from search_modules (hybrid_search); every other tool (get_module,
    # find_by_class, etc.) has no ranking signal of its own, so these stay
    # None for those.
    score: float | None = None
    semantic_rank: int | None = None
    keyword_rank: int | None = None
    identifier_rank: int | None = None


def _turn_cost(response: Any, model: str) -> tuple[int, int, Decimal]:
    tokens_in = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens
    cost = resolve_llm_cost(response, model, tokens_in, tokens_out)
    LLM_CALLS_TOTAL.labels(model, "chat").inc()
    LLM_CALL_COST_USD.labels(model, "chat").observe(float(cost))
    return tokens_in, tokens_out, cost


async def _persist_chat_cost(
    session: AsyncSession, model: str, tokens_in: int, tokens_out: int, cost: Decimal
) -> None:
    session.add(
        AnalysisCache(
            content_hash=f"chat:{uuid.uuid4()}",
            model=model,
            prompt_version=CHAT_PROMPT_VERSION,
            kind="chat",
            response={},
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )
    )
    await session.commit()


def _collect_sources(
    tool_name: str, args: dict[str, Any], result: dict[str, Any], sources: dict[tuple[Any, Any], Source]
) -> None:
    """Record (module_id, relative_path) refs a tool call actually touched, deduped."""

    def _add(
        module_id: int | None,
        module_name: str | None,
        relative_path: str | None = None,
        score: float | None = None,
        semantic_rank: int | None = None,
        keyword_rank: int | None = None,
        identifier_rank: int | None = None,
    ) -> None:
        if module_id is None:
            return
        key = (module_id, relative_path)
        if key not in sources:
            sources[key] = Source(
                module_id=module_id,
                module_name=module_name or "",
                relative_path=relative_path,
                score=score,
                semantic_rank=semantic_rank,
                keyword_rank=keyword_rank,
                identifier_rank=identifier_rank,
            )

    if tool_name == "search_modules":
        for r in result.get("results", []):
            _add(
                r.get("module_id"),
                r.get("module_name"),
                r.get("relative_path"),
                score=r.get("score"),
                semantic_rank=r.get("semantic_rank"),
                keyword_rank=r.get("keyword_rank"),
                identifier_rank=r.get("identifier_rank"),
            )
    elif tool_name == "get_module":
        if result.get("found"):
            _add(result.get("module_id"), result.get("name"))
    elif tool_name == "get_dependencies":
        if result.get("found"):
            _add(args.get("module_id"), result.get("module_name"))
    elif tool_name == "find_by_event":
        for r in result.get("results", []):
            _add(r.get("module_id"), r.get("module_name"))
    elif tool_name == "find_by_class":
        for key in ("defined_in", "overridden_by", "plugins_targeting_it", "is_a_plugin_for"):
            for r in result.get(key, []):
                _add(r.get("module_id"), r.get("module_name"))
    elif tool_name == "read_file":
        if result.get("found"):
            _add(args.get("module_id"), result.get("module_name"), args.get("relative_path"))
    elif tool_name == "list_modules":
        for r in result.get("modules", []):
            _add(r.get("module_id"), r.get("name"))
    elif tool_name == "recommend_module_cleanup":
        for p in result.get("merge_candidates", []):
            _add(p.get("module_a_id"), p.get("module_a_name"))
            _add(p.get("module_b_id"), p.get("module_b_name"))
        for r in result.get("deprecation_candidates", []):
            _add(r.get("module_id"), r.get("name"))


_ENUMERATION_PHRASES = (
    "how many", "count of", "number of", "show all", "show every", "list all", "list every", "every module",
    "all modules",
)


def _looks_like_an_enumeration_question(messages: list[dict[str, Any]]) -> bool:
    """CLAUDE.md's own routing table says counting/"show all" questions must go
    through list_modules (a real SQL count/filter), not search_modules's top-k,
    which is not guaranteed complete -- but that's only ever enforced by the
    system prompt, not by code. This is a narrow, code-level backstop for the
    clearest case: a question that reads like a count or a full listing,
    answered without ever calling list_modules at all.
    """
    last_user_message = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    lowered = last_user_message.lower()
    return any(phrase in lowered for phrase in _ENUMERATION_PHRASES)


async def run_agent(
    session: AsyncSession, messages: list[dict[str, Any]], audience: str
) -> AsyncIterator[dict[str, Any]]:
    """Agentic tool-calling loop over the 7 tools in app.agent.tools, then one final
    streamed turn. Yields plain dict events: {"event": "sources"|"token"|"done", ...}.
    See CLAUDE.md "RAG and the agent" for the design this implements.
    """
    if await is_budget_exceeded(session):
        yield {"event": "error", "detail": "Monthly LLM budget exceeded — cannot answer right now."}
        # Clients wait on "done" to clear loading state (the documented
        # sources/token/done contract) — never leave them hanging on an
        # early-exit path that only ever emits "error".
        yield {"event": "done", "tokens_in": 0, "tokens_out": 0, "cost_usd": "0"}
        return

    llm_config = await resolve_llm_config(session)

    history = [{"role": "system", "content": build_system_prompt(audience)}, *messages]
    sources: dict[tuple[Any, Any], Source] = {}
    tools_called: set[str] = set()
    tokens_in_total = 0
    tokens_out_total = 0
    cost_total = Decimal(0)

    forced_retry_used = False
    enumeration_retry_used = False
    for _round in range(MAX_TOOL_ROUNDS):
        # Rechecked every round, not just once before the loop — up to
        # MAX_TOOL_ROUNDS rounds each make a real, billed LLM call, and the
        # budget can cross its limit partway through a single chat response.
        # Persist whatever was actually spent so far before aborting — those
        # calls already happened and must still reach the budget tracker.
        if await is_budget_exceeded(session):
            yield {"event": "sources", "sources": [vars(s) for s in sources.values()]}
            yield {"event": "error", "detail": "Monthly LLM budget exceeded — cannot answer right now."}
            await _persist_chat_cost(session, llm_config.model, tokens_in_total, tokens_out_total, cost_total)
            yield {"event": "done", "tokens_in": tokens_in_total, "tokens_out": tokens_out_total,
                   "cost_usd": str(cost_total)}
            return

        response = await litellm.acompletion(
            model=llm_config.model,
            api_key=llm_config.api_key,
            api_base=llm_config.api_base,
            messages=history,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            _skip_mcp_handler=True,
        )
        tokens_in, tokens_out, cost = _turn_cost(response, llm_config.model)
        tokens_in_total += tokens_in
        tokens_out_total += tokens_out
        cost_total += cost

        message = response.choices[0].message
        tool_calls = message.tool_calls
        if not tool_calls:
            if not sources and not forced_retry_used:
                # The model answered without ever calling a tool, so the
                # answer-only-from-tool-data contract can't actually be
                # grounded — nudge it once rather than trusting the system
                # prompt alone to prevent fabrication.
                forced_retry_used = True
                history.append(
                    {
                        "role": "user",
                        "content": (
                            "You answered without calling any tools. Call at least one relevant tool "
                            "before answering — if nothing relevant comes back, say plainly that you "
                            "could not find anything."
                        ),
                    }
                )
                continue
            if (
                "list_modules" not in tools_called
                and not enumeration_retry_used
                and _looks_like_an_enumeration_question(messages)
            ):
                # search_modules's top-k is never guaranteed complete, so a
                # counting/"show all" question answered without list_modules
                # (a real SQL count/filter) risks an undercount the system
                # prompt alone doesn't reliably prevent — same one-shot nudge
                # pattern as the no-tool-called case above.
                enumeration_retry_used = True
                history.append(
                    {
                        "role": "user",
                        "content": (
                            "This looks like a counting or \"show all/every\" question. search_modules's top-k "
                            "results are not guaranteed complete — call list_modules (with filters as needed) "
                            "for a real count or full list before answering."
                        ),
                    }
                )
                continue
            break

        history.append(message.model_dump())
        for tc in tool_calls:
            tool_name = tc.function.name
            tools_called.add(tool_name)
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            tool_fn = TOOL_FUNCTIONS.get(tool_name)
            if tool_fn is None:
                result = {"error": f"unknown tool {tool_name}"}
            else:
                try:
                    result = await tool_fn(session, **args)
                except Exception as exc:  # noqa: BLE001
                    # Surface the failure to the model, don't crash the chat.
                    result = {"error": str(exc)}

            _collect_sources(tool_name, args, result, sources)
            history.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
    else:
        history.append(
            {"role": "user", "content": "Tool call limit reached. Answer with what you have so far."}
        )

    yield {"event": "sources", "sources": [vars(s) for s in sources.values()]}

    # The tool loop rechecks the budget every round, but once it exits (via
    # `break`, with no more tool calls) this mandatory final streaming turn ran
    # unconditionally — a budget that crossed its limit in exactly that window
    # still let one more real, billed call through uncounted.
    if await is_budget_exceeded(session):
        yield {"event": "error", "detail": "Monthly LLM budget exceeded — cannot answer right now."}
        await _persist_chat_cost(session, llm_config.model, tokens_in_total, tokens_out_total, cost_total)
        yield {"event": "done", "tokens_in": tokens_in_total, "tokens_out": tokens_out_total,
               "cost_usd": str(cost_total)}
        return

    history.append({"role": "user", "content": FINAL_ANSWER_INSTRUCTION})
    final_turn_kwargs = {}
    if llm_config.model.startswith("anthropic/"):
        # Anthropic binds a "thinking" block's signature to the exact tools list it
        # was generated with, so dropping `tools` here invalidates any thinking
        # block still in history, raising "Invalid signature in thinking block" —
        # keep the same list, with tool_choice="none" blocking further calls.
        final_turn_kwargs = {"tools": TOOL_SCHEMAS, "tool_choice": "none"}
    # Other providers don't have that constraint, and at least Ollama's tool_choice
    # "none" isn't honored (the model still emits a tool_call with no text, verified
    # empirically with llama3.1) — simplest fix there is to drop `tools` entirely.
    stream = await litellm.acompletion(
        model=llm_config.model,
        api_key=llm_config.api_key,
        api_base=llm_config.api_base,
        messages=history,
        stream=True,
        stream_options={"include_usage": True},
        _skip_mcp_handler=True,
        **final_turn_kwargs,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield {"event": "token", "text": delta}
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            tokens_in_total += usage.prompt_tokens
            tokens_out_total += usage.completion_tokens
            raw_cost = getattr(usage, "cost", None)
            # A legitimately reported cost of exactly 0 (free-tier/cached) must
            # not be treated as "no cost info" -- see pricing.py's identical fix
            # for the full-response path; `if raw_cost` here had the same bug.
            stream_cost: Decimal | None = Decimal(str(raw_cost)) if raw_cost is not None else None
            if stream_cost is None or stream_cost < 0:
                stream_cost = compute_cost_usd(llm_config.model, usage.prompt_tokens, usage.completion_tokens)
            cost_total += stream_cost

    await _persist_chat_cost(session, llm_config.model, tokens_in_total, tokens_out_total, cost_total)

    yield {
        "event": "done",
        "tokens_in": tokens_in_total,
        "tokens_out": tokens_out_total,
        "cost_usd": str(cost_total),
    }
