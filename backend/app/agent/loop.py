import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

import litellm
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompt import FINAL_ANSWER_INSTRUCTION, build_system_prompt
from app.agent.tools import TOOL_FUNCTIONS, TOOL_SCHEMAS
from app.analyzer.budget import is_budget_exceeded
from app.analyzer.pricing import compute_cost_usd
from app.analyzer.prompts import CHAT_PROMPT_VERSION
from app.config import settings
from app.models import AnalysisCache

MAX_TOOL_ROUNDS = 6


@dataclass
class Source:
    module_id: int
    module_name: str
    relative_path: str | None = None


def _turn_cost(response) -> tuple[int, int, Decimal]:
    tokens_in = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens
    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception:  # noqa: BLE001 - cost computation must never block the chat response
        cost = None
    if not cost or cost <= 0:
        cost = compute_cost_usd(settings.llm_model, tokens_in, tokens_out)
    return tokens_in, tokens_out, Decimal(str(cost))


def _collect_sources(tool_name: str, args: dict, result: dict, sources: dict[tuple, Source]) -> None:
    """Record (module_id, relative_path) refs a tool call actually touched, deduped."""

    def _add(module_id: int | None, module_name: str | None, relative_path: str | None = None) -> None:
        if module_id is None:
            return
        key = (module_id, relative_path)
        if key not in sources:
            sources[key] = Source(module_id=module_id, module_name=module_name or "", relative_path=relative_path)

    if tool_name == "search_modules":
        for r in result.get("results", []):
            _add(r.get("module_id"), r.get("module_name"), r.get("relative_path"))
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
            _add(args.get("module_id"), None, args.get("relative_path"))
    elif tool_name == "list_modules":
        for r in result.get("modules", []):
            _add(r.get("module_id"), r.get("name"))


async def run_agent(session: AsyncSession, messages: list[dict], audience: str) -> AsyncIterator[dict]:
    """Agentic tool-calling loop over the 7 tools in app.agent.tools, then one final
    streamed turn. Yields plain dict events: {"event": "sources"|"token"|"done", ...}.
    See CLAUDE.md "RAG and the agent" for the design this implements.
    """
    if await is_budget_exceeded(session):
        yield {"event": "error", "detail": "Monthly LLM budget exceeded — cannot answer right now."}
        return

    history = [{"role": "system", "content": build_system_prompt(audience)}, *messages]
    sources: dict[tuple, Source] = {}
    tokens_in_total = 0
    tokens_out_total = 0
    cost_total = Decimal("0")

    for _round in range(MAX_TOOL_ROUNDS):
        response = await litellm.acompletion(
            model=settings.llm_model,
            messages=history,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            _skip_mcp_handler=True,
        )
        tokens_in, tokens_out, cost = _turn_cost(response)
        tokens_in_total += tokens_in
        tokens_out_total += tokens_out
        cost_total += cost

        message = response.choices[0].message
        tool_calls = message.tool_calls
        if not tool_calls:
            break

        history.append(message.model_dump())
        for tc in tool_calls:
            tool_name = tc.function.name
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
                except Exception as exc:  # noqa: BLE001 - surface the failure to the model, don't crash the chat
                    result = {"error": str(exc)}

            _collect_sources(tool_name, args, result, sources)
            history.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
    else:
        history.append(
            {"role": "user", "content": "Tool call limit reached. Answer with what you have so far."}
        )

    yield {"event": "sources", "sources": [vars(s) for s in sources.values()]}

    history.append({"role": "user", "content": FINAL_ANSWER_INSTRUCTION})
    stream = await litellm.acompletion(
        model=settings.llm_model,
        messages=history,
        # Keep the same tools list as the tool-calling rounds above: Anthropic binds a
        # "thinking" block's signature to the exact tools list it was generated with, and
        # dropping `tools` here invalidates any thinking block still in history, raising
        # "Invalid signature in thinking block" — tool_choice="none" blocks further calls
        # without changing that list.
        tools=TOOL_SCHEMAS,
        tool_choice="none",
        stream=True,
        stream_options={"include_usage": True},
        _skip_mcp_handler=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield {"event": "token", "text": delta}
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            tokens_in_total += usage.prompt_tokens
            tokens_out_total += usage.completion_tokens
            cost = getattr(usage, "cost", None)
            if not cost:
                cost = compute_cost_usd(settings.llm_model, usage.prompt_tokens, usage.completion_tokens)
            cost_total += Decimal(str(cost))

    session.add(
        AnalysisCache(
            content_hash=f"chat:{uuid.uuid4()}",
            model=settings.llm_model,
            prompt_version=CHAT_PROMPT_VERSION,
            kind="chat",
            response={},
            tokens_in=tokens_in_total,
            tokens_out=tokens_out_total,
            cost_usd=cost_total,
        )
    )
    await session.commit()

    yield {
        "event": "done",
        "tokens_in": tokens_in_total,
        "tokens_out": tokens_out_total,
        "cost_usd": str(cost_total),
    }
