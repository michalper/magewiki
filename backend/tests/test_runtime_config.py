import pytest
from sqlalchemy import delete

from app.config import settings
from app.models import RuntimeLlmConfig
from app.runtime_config import (
    resolve_embedding_config,
    resolve_llm_config,
    resolve_synthesis_llm_config,
)


@pytest.fixture(autouse=True)
async def _clear_runtime_config(db_session):
    await db_session.execute(delete(RuntimeLlmConfig))
    await db_session.commit()
    yield
    await db_session.execute(delete(RuntimeLlmConfig))
    await db_session.commit()


@pytest.mark.asyncio
async def test_resolve_llm_config_falls_back_to_env_defaults(db_session):
    config = await resolve_llm_config(db_session)
    assert config.model == settings.llm_model
    assert config.api_key is None
    assert config.api_base is None


@pytest.mark.asyncio
async def test_resolve_llm_config_with_model_override_only(db_session):
    db_session.add(RuntimeLlmConfig(id=1, llm_model="deepseek/deepseek-chat"))
    await db_session.commit()

    config = await resolve_llm_config(db_session)
    assert config.model == "deepseek/deepseek-chat"
    assert config.api_key is None
    assert config.api_base is None


@pytest.mark.asyncio
async def test_resolve_llm_config_with_model_and_key_override(db_session):
    db_session.add(RuntimeLlmConfig(id=1, llm_model="deepseek/deepseek-chat", llm_api_key="sk-test-123"))
    await db_session.commit()

    config = await resolve_llm_config(db_session)
    assert config.model == "deepseek/deepseek-chat"
    assert config.api_key == "sk-test-123"
    assert config.api_base is None


@pytest.mark.asyncio
async def test_resolve_llm_config_ollama_model_falls_back_to_settings_base_url(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ollama_base_url", "http://host.docker.internal:11434")
    db_session.add(RuntimeLlmConfig(id=1, llm_model="ollama_chat/llama3.1"))
    await db_session.commit()

    config = await resolve_llm_config(db_session)
    assert config.model == "ollama_chat/llama3.1"
    assert config.api_base == "http://host.docker.internal:11434"


@pytest.mark.asyncio
async def test_resolve_llm_config_ollama_explicit_api_base_wins_over_settings(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ollama_base_url", "http://host.docker.internal:11434")
    db_session.add(
        RuntimeLlmConfig(id=1, llm_model="ollama_chat/llama3.1", llm_api_base="http://custom-ollama:11434")
    )
    await db_session.commit()

    config = await resolve_llm_config(db_session)
    assert config.api_base == "http://custom-ollama:11434"


@pytest.mark.asyncio
async def test_resolve_embedding_config_falls_back_to_env_defaults(db_session):
    config = await resolve_embedding_config(db_session)
    assert config.model == settings.embedding_model
    assert config.api_key is None
    assert config.api_base is None


@pytest.mark.asyncio
async def test_resolve_embedding_config_with_override(db_session):
    db_session.add(RuntimeLlmConfig(id=1, embedding_model="openai/text-embedding-3-large", embedding_api_key="sk-emb"))
    await db_session.commit()

    config = await resolve_embedding_config(db_session)
    assert config.model == "openai/text-embedding-3-large"
    assert config.api_key == "sk-emb"


@pytest.mark.asyncio
async def test_resolve_llm_and_embedding_configs_are_independent(db_session):
    db_session.add(RuntimeLlmConfig(id=1, llm_model="deepseek/deepseek-chat"))
    await db_session.commit()

    llm_config = await resolve_llm_config(db_session)
    embedding_config = await resolve_embedding_config(db_session)

    assert llm_config.model == "deepseek/deepseek-chat"
    assert embedding_config.model == settings.embedding_model


@pytest.mark.asyncio
async def test_resolve_synthesis_llm_config_falls_back_to_llm_config_when_unset(db_session, monkeypatch):
    monkeypatch.setattr(settings, "synthesis_model", "")
    db_session.add(RuntimeLlmConfig(id=1, llm_model="deepseek/deepseek-chat", llm_api_key="sk-test-123"))
    await db_session.commit()

    config = await resolve_synthesis_llm_config(db_session)
    assert config.model == "deepseek/deepseek-chat"
    assert config.api_key == "sk-test-123"


@pytest.mark.asyncio
async def test_resolve_synthesis_llm_config_overrides_model_but_reuses_llm_credentials(db_session, monkeypatch):
    monkeypatch.setattr(settings, "synthesis_model", "anthropic/claude-sonnet-5-5")
    db_session.add(RuntimeLlmConfig(id=1, llm_model="anthropic/claude-haiku-5-5", llm_api_key="sk-test-456"))
    await db_session.commit()

    config = await resolve_synthesis_llm_config(db_session)
    assert config.model == "anthropic/claude-sonnet-5-5"
    assert config.api_key == "sk-test-456"
