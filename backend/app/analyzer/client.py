import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeVar

import litellm
from pydantic import ValidationError

from app.analyzer.facts import ModuleFacts
from app.analyzer.pricing import compute_cost_usd
from app.analyzer.prompts import build_file_summary_prompt, build_module_synthesis_prompt
from app.analyzer.schemas import FileSummary, ModuleDoc

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)
_MAX_ATTEMPTS = 2
T = TypeVar("T")


@dataclass
class LlmCallResult:
    response_json: dict
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal


def _strip_markdown_fence(text: str) -> str:
    match = _FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text.strip()


def _result_from_response(response, response_json: dict, model: str) -> LlmCallResult:
    tokens_in = response.usage.prompt_tokens
    tokens_out = response.usage.completion_tokens

    cost: Decimal | None = None
    try:
        raw_cost = litellm.completion_cost(completion_response=response)
        cost = Decimal(str(raw_cost)) if raw_cost else None
    except Exception:  # noqa: BLE001 - cost computation must never block analysis
        cost = None
    if not cost or cost <= 0:
        cost = compute_cost_usd(model, tokens_in, tokens_out)

    return LlmCallResult(
        response_json=response_json,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
    )


async def _call_tool_use(
    prompt: str,
    schema: dict,
    max_tokens: int,
    model: str,
    api_key: str | None,
    api_base: str | None,
    validate: Callable[[dict], T],
    tool_name: str = "emit_result",
) -> tuple[T, LlmCallResult] | None:
    """Try structured output via forced tool-use, retrying with corrective
    feedback if the response is syntactically valid JSON but fails `validate`
    — forced tool-use heavily biases a model toward the schema but does not
    guarantee every required field is actually present (confirmed in
    production: ModuleDoc's pm_text/dev_text/description are occasionally
    omitted even though the JSON Schema marks them required). Returns None
    (not an exception) only if the provider doesn't honor tool_choice/
    tool_calls the way Anthropic/OpenAI-style providers do, or never
    produces parseable JSON at all, so the caller can fall back to
    plain-JSON prompting — this keeps the analyzer usable with any
    LiteLLM-supported model (BYOK), not just providers with reliable forced
    function calling.
    """
    last_error: str | None = None
    for attempt in range(_MAX_ATTEMPTS):
        attempt_prompt = (
            prompt
            if attempt == 0
            else f"{prompt}\n\nYour previous response was invalid: {last_error}. "
            "Call the tool again with a corrected, complete result — every required field filled in."
        )
        try:
            response = await litellm.acompletion(
                model=model,
                api_key=api_key,
                api_base=api_base,
                messages=[{"role": "user", "content": attempt_prompt}],
                tools=[{"type": "function", "function": {"name": tool_name, "parameters": schema}}],
                tool_choice={"type": "function", "function": {"name": tool_name}},
                max_tokens=max_tokens,
                _skip_mcp_handler=True,
            )
        except Exception:  # noqa: BLE001 - provider may reject tools/tool_choice entirely
            return None

        tool_calls = response.choices[0].message.tool_calls
        if not tool_calls:
            return None

        try:
            response_json = json.loads(tool_calls[0].function.arguments)
        except json.JSONDecodeError:
            return None  # malformed tool-call args aren't worth retrying this way; fall back instead

        try:
            validated = validate(response_json)
        except ValidationError as exc:
            last_error = str(exc)
            continue

        return validated, _result_from_response(response, response_json, model)

    return None  # exhausted retries without a provider-level rejection — let plain-JSON try instead


async def _call_plain_json(
    prompt: str,
    schema: dict,
    max_tokens: int,
    model: str,
    api_key: str | None,
    api_base: str | None,
    validate: Callable[[dict], T],
) -> tuple[T, LlmCallResult]:
    """Fallback for providers without reliable forced tool-choice: ask for raw JSON,
    with one corrective re-prompt if the first response doesn't parse, or parses
    but fails `validate` (e.g. a required field was omitted).
    """
    instructions = (
        f"{prompt}\n\nRespond with ONLY a single JSON object matching this JSON schema — "
        f"no markdown code fences, no explanation, just the JSON object:\n{json.dumps(schema)}"
    )

    last_error: str | None = None
    for attempt in range(_MAX_ATTEMPTS):
        attempt_prompt = (
            instructions
            if attempt == 0
            else f"{instructions}\n\nYour previous response was invalid ({last_error}). "
            "Return ONLY the corrected, complete JSON object this time."
        )
        response = await litellm.acompletion(
            model=model,
            api_key=api_key,
            api_base=api_base,
            messages=[{"role": "user", "content": attempt_prompt}],
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or ""
        try:
            response_json = json.loads(_strip_markdown_fence(content))
        except json.JSONDecodeError as exc:
            last_error = f"not valid JSON: {exc}"
            continue
        try:
            validated = validate(response_json)
        except ValidationError as exc:
            last_error = str(exc)
            continue
        return validated, _result_from_response(response, response_json, model)

    raise ValueError(f"LLM did not return a valid, schema-compliant JSON object after retry: {last_error}")


async def _call_llm(
    prompt: str,
    schema: dict,
    model: str,
    api_key: str | None,
    api_base: str | None,
    validate: Callable[[dict], T],
    max_tokens: int = 2000,
) -> tuple[T, LlmCallResult]:
    result = await _call_tool_use(prompt, schema, max_tokens, model, api_key, api_base, validate)
    if result is not None:
        return result
    return await _call_plain_json(prompt, schema, max_tokens, model, api_key, api_base, validate)


async def summarize_file(
    relative_path: str, content: str, *, model: str, api_key: str | None, api_base: str | None = None
) -> tuple[FileSummary, LlmCallResult]:
    prompt = build_file_summary_prompt(relative_path, content)
    return await _call_llm(
        prompt, FileSummary.model_json_schema(), model, api_key, api_base, FileSummary.model_validate, max_tokens=800
    )


async def synthesize_module_doc(
    facts: ModuleFacts, known_sources: set[str], *, model: str, api_key: str | None, api_base: str | None = None
) -> tuple[ModuleDoc, LlmCallResult]:
    prompt = build_module_synthesis_prompt(facts)

    def _validate(data: dict) -> ModuleDoc:
        return ModuleDoc.model_validate(data, context={"known_sources": known_sources})

    return await _call_llm(
        prompt, ModuleDoc.model_json_schema(), model, api_key, api_base, _validate, max_tokens=16000
    )
