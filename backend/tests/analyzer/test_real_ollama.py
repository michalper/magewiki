import pytest

from app.analyzer.client import summarize_file
from app.config import settings
from tests.conftest import requires_ollama

OLLAMA_MODEL = "ollama_chat/llama3.1"


@requires_ollama
@pytest.mark.ollama
@pytest.mark.asyncio
async def test_real_ollama_summarizes_a_file():
    """Real local Ollama call (free, no API key) — verified empirically that
    ollama_chat/llama3.1 honors forced tool-use for structured output (see
    CLAUDE.md "LLM" row: Ollama as a BYOK option).
    """
    content = (
        "<?xml version=\"1.0\"?>\n"
        "<config>\n"
        "    <module name=\"Vendor_Module\" setup_version=\"1.0.0\"/>\n"
        "</config>\n"
    )
    summary, result = await summarize_file(
        "etc/module.xml", content, model=OLLAMA_MODEL, api_key=None, api_base=settings.ollama_base_url
    )

    assert summary.file_summary
    assert len(summary.file_summary) > 10
    assert result.tokens_in > 0
