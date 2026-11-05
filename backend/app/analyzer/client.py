import json
import re
from dataclasses import dataclass
from decimal import Decimal

import litellm

from app.analyzer.facts import ModuleFacts
from app.analyzer.pricing import compute_cost_usd
from app.analyzer.prompts import build_file_summary_prompt, build_module_synthesis_prompt
from app.analyzer.schemas import FileSummary, ModuleDoc
from app.config import settings

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


@dataclass
class LlmCallResult:
    response_json: dict
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal


def _strip_markdown_fence(text: str) -> str:
    match = _FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text.strip()


def _result_from_response(response, response_json: dict) -> LlmCallResult:
    tokens_in = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens

    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception:  # noqa: BLE001 - cost computation must never block analysis
        cost = None
    if not cost or cost <= 0:
        cost = compute_cost_usd(settings.llm_model, tokens_in, tokens_out)

    return LlmCallResult(
        response_json=response_json,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=Decimal(str(cost)),
    )


async def _call_tool_use(
    prompt: str, schema: dict, max_tokens: int, tool_name: str = "emit_result"
) -> LlmCallResult | None:
    """Try structured output via forced tool-use. Returns None (not an exception) if
    the provider doesn't honor tool_choice/tool_calls the way Anthropic/OpenAI-style
    providers do, so the caller can fall back to plain-JSON prompting — this keeps
    the analyzer usable with any LiteLLM-supported model (BYOK), not just providers
    with reliable forced function calling.
    """
    try:
        response = await litellm.acompletion(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
            tools=[{"type": "function", "function": {"name": tool_name, "parameters": schema}}],
            tool_choice={"type": "function", "function": {"name": tool_name}},
            max_tokens=max_tokens,
        )
    except Exception:  # noqa: BLE001 - provider may reject tools/tool_choice entirely
        return None

    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        return None

    try:
        response_json = json.loads(tool_calls[0].function.arguments)
    except json.JSONDecodeError:
        return None

    return _result_from_response(response, response_json)


async def _call_plain_json(prompt: str, schema: dict, max_tokens: int) -> LlmCallResult:
    """Fallback for providers without reliable forced tool-choice: ask for raw JSON,
    with one corrective re-prompt if the first response doesn't parse.
    """
    instructions = (
        f"{prompt}\n\nRespond with ONLY a single JSON object matching this JSON schema — "
        f"no markdown code fences, no explanation, just the JSON object:\n{json.dumps(schema)}"
    )

    last_error: str | None = None
    for attempt in range(2):
        attempt_prompt = (
            instructions
            if attempt == 0
            else f"{instructions}\n\nYour previous response was not valid JSON ({last_error}). "
            "Return ONLY the corrected JSON object this time."
        )
        response = await litellm.acompletion(
            model=settings.llm_model,
            messages=[{"role": "user", "content": attempt_prompt}],
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or ""
        try:
            response_json = json.loads(_strip_markdown_fence(content))
        except json.JSONDecodeError as exc:
            last_error = str(exc)
            continue
        return _result_from_response(response, response_json)

    raise ValueError(f"LLM did not return valid JSON after retry: {last_error}")


async def _call_llm(prompt: str, schema: dict, max_tokens: int = 2000) -> LlmCallResult:
    result = await _call_tool_use(prompt, schema, max_tokens)
    if result is not None:
        return result
    return await _call_plain_json(prompt, schema, max_tokens)


async def summarize_file(relative_path: str, content: str) -> tuple[FileSummary, LlmCallResult]:
    prompt = build_file_summary_prompt(relative_path, content)
    result = await _call_llm(prompt, FileSummary.model_json_schema(), max_tokens=800)
    summary = FileSummary.model_validate(result.response_json)
    return summary, result


async def synthesize_module_doc(
    facts: ModuleFacts, known_sources: set[str]
) -> tuple[ModuleDoc, LlmCallResult]:
    prompt = build_module_synthesis_prompt(facts)
    result = await _call_llm(prompt, ModuleDoc.model_json_schema(), max_tokens=4000)
    doc = ModuleDoc.model_validate(result.response_json, context={"known_sources": known_sources})
    return doc, result
