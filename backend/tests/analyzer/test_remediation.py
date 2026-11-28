import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.analyzer.embeddings import hash_text
from app.analyzer.prompts import REMEDIATION_PROMPT_VERSION, build_remediation_prompt
from app.analyzer.remediation import get_or_create_remediation
from app.config import settings
from app.models import AnalysisCache
from app.runtime_config import resolve_llm_config


def _tool_response(remediation: str) -> SimpleNamespace:
    tool_call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps({"remediation": remediation})))
    message = SimpleNamespace(tool_calls=[tool_call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=80, completion_tokens=40),
    )


@pytest.mark.asyncio
async def test_a_real_call_returns_and_caches_the_remediation_text(db_session, monkeypatch):
    calls = 0

    async def fake_acompletion(**kwargs):
        nonlocal calls
        calls += 1
        return _tool_response("Remove the hardcoded key and load it from a secret manager instead.")

    monkeypatch.setattr("app.analyzer.client.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.analyzer.client.litellm.completion_cost", lambda **k: 0.0005)

    message = f"unique message {hash_text('first-call')}"
    result = await get_or_create_remediation(
        db_session, "Vendor_Module", "hardcoded_secret", "blocking", "Model/Thing.php", 12, message
    )

    assert result == "Remove the hardcoded key and load it from a secret manager instead."
    assert calls == 1

    row = (
        await db_session.execute(
            AnalysisCache.__table__.select()
            .where(AnalysisCache.kind == "remediation")
            .order_by(AnalysisCache.id.desc())
            .limit(1)
        )
    ).first()
    assert row is not None
    assert row.prompt_version == REMEDIATION_PROMPT_VERSION
    assert row.response == {"remediation": "Remove the hardcoded key and load it from a secret manager instead."}

    # A second call for the exact same finding content must hit the cache,
    # not call the LLM again.
    second_result = await get_or_create_remediation(
        db_session, "Vendor_Module", "hardcoded_secret", "blocking", "Model/Thing.php", 12, message
    )
    assert second_result == result
    assert calls == 1


@pytest.mark.asyncio
async def test_cache_hit_returns_cached_text_without_a_new_llm_call(db_session, monkeypatch):
    message = f"unique message {hash_text('cache-hit')}"
    content_hash = hash_text(f"composer_completeness|{None}|{None}|{message}")
    config = await resolve_llm_config(db_session)
    db_session.add(
        AnalysisCache(
            content_hash=content_hash,
            model=config.model,
            prompt_version=REMEDIATION_PROMPT_VERSION,
            kind="remediation",
            response={"remediation": "Already-cached remediation text."},
            tokens_in=1,
            tokens_out=1,
            cost_usd=Decimal("0.0001"),
        )
    )
    await db_session.commit()

    async def fail_if_called(**kwargs):
        raise AssertionError("must not call the LLM on a cache hit")

    monkeypatch.setattr("app.analyzer.client.litellm.acompletion", fail_if_called)

    result = await get_or_create_remediation(
        db_session, "Vendor_Module", "composer_completeness", "warning", None, None, message
    )

    assert result == "Already-cached remediation text."


@pytest.mark.asyncio
async def test_budget_exceeded_returns_none_without_calling_the_llm(db_session, monkeypatch):
    monkeypatch.setattr(settings, "llm_monthly_budget_usd", -1.0)  # already exceeded, unconditionally

    called = False

    async def fake_acompletion(**kwargs):
        nonlocal called
        called = True
        return _tool_response("should not happen")

    monkeypatch.setattr("app.analyzer.client.litellm.acompletion", fake_acompletion)

    message = f"unique message {hash_text('over-budget')}"
    result = await get_or_create_remediation(
        db_session, "Vendor_Module", "hardcoded_secret", "blocking", "Model/Thing.php", 1, message
    )

    assert result is None
    assert called is False


def test_remediation_prompt_only_interpolates_the_given_finding_fields():
    prompt = build_remediation_prompt(
        "Vendor_Module", "hardcoded_secret", "blocking", "Model/Thing.php", 12, "An API key was found."
    )

    assert "Vendor_Module" in prompt
    assert "hardcoded_secret" in prompt
    assert "blocking" in prompt
    assert "Model/Thing.php:12" in prompt
    assert "An API key was found." in prompt
    assert "never invent" in prompt.lower()


def test_remediation_prompt_handles_a_missing_file_path_and_line():
    prompt = build_remediation_prompt("Vendor_Module", "composer_completeness", "warning", None, None, "No tests.")

    assert "unknown location" in prompt
