import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.analyzer.client import summarize_file, synthesize_module_doc
from app.analyzer.facts import ModuleFacts


def _tool_use_response(arguments: dict) -> SimpleNamespace:
    tool_call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(arguments)))
    message = SimpleNamespace(tool_calls=[tool_call], content=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


def _plain_json_response(data: dict) -> SimpleNamespace:
    message = SimpleNamespace(tool_calls=None, content=json.dumps(data))
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


def _no_tool_call_response() -> SimpleNamespace:
    message = SimpleNamespace(tool_calls=None, content=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


@pytest.mark.asyncio
async def test_summarize_file_retries_tool_use_when_a_required_field_is_missing(monkeypatch):
    """Regression test: forced tool-use heavily biases a model toward the JSON
    Schema but doesn't guarantee every required field is present — confirmed
    in production, ModuleDoc's pm_text/dev_text/description were occasionally
    omitted even though the schema marks them required, and the resulting
    Pydantic ValidationError used to propagate straight out uncaught, failing
    the whole module instead of retrying with corrective feedback the way a
    malformed-JSON response already did.
    """
    responses = [
        _tool_use_response({"notable_behavior": "does something"}),  # missing required file_summary
        _tool_use_response({"file_summary": "Handles checkout totals.", "notable_behavior": None}),
    ]

    async def fake_acompletion(**kwargs):
        return responses.pop(0)

    monkeypatch.setattr("app.analyzer.client.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.analyzer.client.litellm.completion_cost", lambda **k: 0.001)

    summary, result = await summarize_file(
        "Model/Total.php", "<?php class Total {}", model="anthropic/claude-haiku-5-5", api_key="test-key"
    )

    assert summary.file_summary == "Handles checkout totals."
    # The discarded first attempt still made a real, billed LLM call — its cost
    # must still reach the budget tracker, not just the attempt that ultimately
    # succeeded. Both attempts cost 100/50 tokens and $0.001 (per the mocks
    # above), so the returned total must reflect both, not just the second.
    assert result.tokens_in == 200
    assert result.tokens_out == 100
    assert result.cost_usd == Decimal("0.002")


@pytest.mark.asyncio
async def test_summarize_file_raises_after_exhausting_retries_on_persistent_validation_failure(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _tool_use_response({"notable_behavior": "still missing file_summary"})

    monkeypatch.setattr("app.analyzer.client.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.analyzer.client.litellm.completion_cost", lambda **k: 0.001)

    with pytest.raises(ValueError, match="did not return a valid, schema-compliant JSON"):
        await summarize_file(
            "Model/Total.php", "<?php class Total {}", model="anthropic/claude-haiku-5-5", api_key="test-key"
        )


@pytest.mark.asyncio
async def test_call_plain_json_retries_when_a_required_field_is_missing(monkeypatch):
    """Same regression, exercised via the plain-JSON fallback path (providers
    without reliable forced tool-choice) rather than tool-use.
    """
    responses = [
        _no_tool_call_response(),  # tool-use unsupported -> falls back to plain JSON
        _plain_json_response({"notable_behavior": "does something"}),  # missing file_summary
        _plain_json_response({"file_summary": "Handles checkout totals."}),
    ]

    async def fake_acompletion(**kwargs):
        return responses.pop(0)

    monkeypatch.setattr("app.analyzer.client.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.analyzer.client.litellm.completion_cost", lambda **k: 0.001)

    summary, result = await summarize_file(
        "Model/Total.php", "<?php class Total {}", model="some/other-model", api_key="test-key"
    )

    assert summary.file_summary == "Handles checkout totals."
    # Same cost-accounting fix within the plain-JSON fallback's own 2 attempts
    # (the first, tool-use-unsupported attempt's cost is a separate, documented,
    # out-of-scope gap — see client.py's comment on _call_tool_use's early
    # "return None" paths).
    assert result.tokens_in == 200
    assert result.tokens_out == 100
    assert result.cost_usd == Decimal("0.002")


@pytest.mark.asyncio
async def test_synthesize_module_doc_retries_when_pm_text_and_dev_text_are_missing(monkeypatch):
    """The exact shape of the real production failure: a large/complex module
    synthesis response missing pm_text and dev_text.
    """
    complete = {
        "summary": "Ordo automation module.",
        "description": "Automates order workflows.",
        "confidence": 0.8,
        "pm_text": "Automates repetitive order tasks for the ops team.",
        "dev_text": "Hooks into sales_order_save_after.",
    }
    incomplete = {k: v for k, v in complete.items() if k not in ("pm_text", "dev_text")}
    responses = [_tool_use_response(incomplete), _tool_use_response(complete)]

    async def fake_acompletion(**kwargs):
        return responses.pop(0)

    monkeypatch.setattr("app.analyzer.client.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.analyzer.client.litellm.completion_cost", lambda **k: 0.001)

    facts = ModuleFacts(
        name="Ordo_Automation", composer_name=None, composer_type=None, license=None,
        enabled=None, setup_version=None,
    )

    doc, _ = await synthesize_module_doc(
        facts, known_sources=set(), known_config_paths=set(), model="anthropic/claude-haiku-5-5", api_key="test-key"
    )

    assert doc.pm_text == complete["pm_text"]
    assert doc.dev_text == complete["dev_text"]
