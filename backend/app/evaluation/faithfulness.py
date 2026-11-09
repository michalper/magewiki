"""LLM-as-judge faithfulness check: does the agent's own answer actually say
only things its cited sources support? A separate axis from retrieval
quality (recall@k/MRR) -- the agent can retrieve the right chunks and still
overstate or misread them in its final answer. See CLAUDE.md's "LLM-judge
faithfulness eval" decision note.

Deliberately eval-only, not wired into the production chat path: it's a
second real LLM call per question, and the live anti-hallucination design
(docs/architecture.md) already constrains the agent's own system prompt to
answer only from tool results -- this checks whether that constraint actually
held, after the fact, not a runtime safeguard.
"""

import json

import litellm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk

JUDGE_PROMPT_VERSION = "faithfulness_judge_v1"


class FaithfulnessVerdict(BaseModel):
    grounded: bool
    unsupported_claims: list[str] = []
    reasoning: str


async def fetch_cited_source_texts(session: AsyncSession, sources: list[dict]) -> list[tuple[str, str]]:
    """Real chunk content for each source the agent cited, fetched fresh from
    the database -- the judge compares the answer against this, never against
    the agent's own (possibly already-wrong) description of what a source
    says.
    """
    texts: list[tuple[str, str]] = []
    seen: set[tuple] = set()
    for source in sources:
        module_id = source.get("module_id")
        relative_path = source.get("relative_path")
        key = (module_id, relative_path)
        if module_id is None or key in seen:
            continue
        seen.add(key)

        if relative_path is None:
            stmt = select(Chunk).where(Chunk.module_id == module_id, Chunk.chunk_type == "module")
        else:
            stmt = select(Chunk).where(Chunk.module_id == module_id, Chunk.relative_path == relative_path)
        chunks = (await session.scalars(stmt)).all()

        label = source.get("module_name", f"module {module_id}")
        if relative_path:
            label = f"{label} / {relative_path}"
        for chunk in chunks:
            texts.append((label, chunk.text))
    return texts


def build_faithfulness_judge_prompt(question: str, answer: str, source_texts: list[tuple[str, str]]) -> str:
    lines = [
        (
            "You are fact-checking an AI assistant's answer against its own cited "
            "sources. Below is a user's question, the assistant's answer, and the "
            "actual content of every source it cited. Check every factual claim in "
            "the answer: is it actually supported by the source content, or does the "
            "answer state something the sources don't say (an unsupported claim)? "
            "Don't penalize reasonable paraphrasing or summarization -- only flag a "
            "claim that isn't backed by the sources at all, or contradicts them.\n\n"
        ),
        f"Question: {question}\n\n",
        f"Assistant's answer:\n{answer}\n\n",
        "Cited sources:\n",
    ]
    if not source_texts:
        lines.append("(none -- the answer cited no sources at all)\n")
    for label, text in source_texts:
        lines.append(f"--- {label} ---\n{text}\n\n")
    lines.append(
        "List every unsupported claim found (empty list if none), and say whether "
        "the answer overall is grounded (true only if there are zero unsupported claims)."
    )
    return "".join(lines)


async def judge_faithfulness(
    session: AsyncSession,
    question: str,
    answer: str,
    sources: list[dict],
    *,
    model: str,
    api_key: str | None,
    api_base: str | None = None,
) -> FaithfulnessVerdict:
    """No retry, no fallback: unlike runtime reranking, a failure here is a
    real problem worth seeing in the eval report, not something to silently
    paper over. Callers (the eval runner) catch exceptions per-question so one
    bad judge call doesn't abort an entire eval run.
    """
    source_texts = await fetch_cited_source_texts(session, sources)
    prompt = build_faithfulness_judge_prompt(question, answer, source_texts)

    response = await litellm.acompletion(
        model=model,
        api_key=api_key,
        api_base=api_base,
        messages=[{"role": "user", "content": prompt}],
        tools=[
            {
                "type": "function",
                "function": {"name": "submit_verdict", "parameters": FaithfulnessVerdict.model_json_schema()},
            }
        ],
        tool_choice={"type": "function", "function": {"name": "submit_verdict"}},
        max_tokens=800,
        _skip_mcp_handler=True,
    )
    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise RuntimeError("faithfulness judge did not return a verdict (no tool call)")
    data = json.loads(tool_calls[0].function.arguments)
    return FaithfulnessVerdict.model_validate(data)
