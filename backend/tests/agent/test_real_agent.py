from pathlib import Path

import pytest
from sqlalchemy import delete, select

from app.agent.loop import run_agent
from app.config import settings
from app.models import Module, RuntimeLlmConfig
from app.scanner.orchestrator import scan_repository
from tests.conftest import requires_anthropic_key, requires_ollama


async def _delete_module_if_present(session, repo_root: str, name: str) -> None:
    existing = await session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == name))
    if existing is not None:
        await session.execute(delete(Module).where(Module.id == existing.id))
        await session.commit()


@requires_anthropic_key
@pytest.mark.llm
@pytest.mark.asyncio
async def test_real_agent_cites_the_right_module_for_a_plugin_question(demo_store_path: Path, db_session):
    """Real Anthropic tool-calling + streaming end-to-end. Deliberately asks a
    question answerable via find_by_class (deterministic SQL), not search_modules
    (which needs real OpenAI embeddings — a separate, already-covered concern) —
    see CLAUDE.md "RAG and the agent" / anti-hallucination rules: every claim must
    cite its module, and this question has exactly one correct citation.
    """
    repo_root = str(demo_store_path.resolve())
    await _delete_module_if_present(db_session, repo_root, "Vendor_Module")
    await scan_repository(repo_root, db_session)
    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))

    question = (
        "Which module defines a plugin on Magento\\Quote\\Model\\Quote\\Address\\Total\\Collector? "
        "Answer with just the module name and a one-sentence citation."
    )
    events = [e async for e in run_agent(db_session, [{"role": "user", "content": question}], "dev")]

    sources_event = next(e for e in events if e["event"] == "sources")
    cited_module_ids = {s["module_id"] for s in sources_event["sources"]}
    assert module.id in cited_module_ids

    final_text = "".join(e["text"] for e in events if e["event"] == "token")
    assert "Vendor_Module" in final_text

    assert any(e["event"] == "done" for e in events)


@requires_ollama
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_real_agent_with_ollama_cites_the_right_module(demo_store_path: Path, db_session):
    """Same end-to-end check as the Anthropic test above, but against a real local
    Ollama server (llama3.1, which Ollama itself tags with "tools" capability) —
    verified empirically that it reliably calls tools and streams a real final
    answer once run_agent.py's model-specific tool_choice="none" workaround (see
    agent/loop.py) is skipped for non-Anthropic providers.
    """
    repo_root = str(demo_store_path.resolve())
    await _delete_module_if_present(db_session, repo_root, "Vendor_Module")
    await scan_repository(repo_root, db_session)
    module = await db_session.scalar(select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_Module"))

    db_session.add(RuntimeLlmConfig(id=1, llm_model="ollama_chat/llama3.1", llm_api_base=settings.ollama_base_url))
    await db_session.commit()

    try:
        question = (
            "Which module defines a plugin on Magento\\Quote\\Model\\Quote\\Address\\Total\\Collector? "
            "Answer with just the module name and a one-sentence citation."
        )
        events = [e async for e in run_agent(db_session, [{"role": "user", "content": question}], "dev")]

        sources_event = next(e for e in events if e["event"] == "sources")
        cited_module_ids = {s["module_id"] for s in sources_event["sources"]}
        assert module.id in cited_module_ids

        final_text = "".join(e["text"] for e in events if e["event"] == "token")
        assert final_text.strip()

        assert any(e["event"] == "done" for e in events)
    finally:
        await db_session.execute(delete(RuntimeLlmConfig).where(RuntimeLlmConfig.id == 1))
        await db_session.commit()
