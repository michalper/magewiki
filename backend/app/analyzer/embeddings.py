import hashlib
from decimal import Decimal

import litellm

from app.analyzer.client import LlmCallResult
from app.analyzer.pricing import compute_cost_usd
from app.analyzer.schemas import ModuleDoc


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def embed_text(
    text: str, *, model: str, api_key: str | None, api_base: str | None = None
) -> tuple[list[float], LlmCallResult]:
    response = await litellm.aembedding(model=model, api_key=api_key, api_base=api_base, input=[text])
    vector = response.data[0]["embedding"]
    tokens_in = response.usage.prompt_tokens

    try:
        cost = litellm.completion_cost(completion_response=response)
    except Exception:  # noqa: BLE001 - cost computation must never block embedding
        cost = None
    if not cost or cost <= 0:
        cost = compute_cost_usd(model, tokens_in, 0)

    result = LlmCallResult(
        response_json={"embedding": vector},
        tokens_in=tokens_in,
        tokens_out=0,
        cost_usd=Decimal(str(cost)),
    )
    return vector, result


async def embed_query_text(
    query: str, *, model: str, api_key: str | None, api_base: str | None = None
) -> list[float]:
    vector, _result = await embed_text(query, model=model, api_key=api_key, api_base=api_base)
    return vector


def build_module_chunk_text(doc: ModuleDoc) -> str:
    parts = [doc.summary, doc.description]
    if doc.features:
        parts.append("Features: " + "; ".join(f"{f.name}: {f.description}" for f in doc.features))
    if doc.integrations:
        parts.append("Integrations: " + "; ".join(f"{i.name}: {i.description}" for i in doc.integrations))
    if doc.tags:
        parts.append("Tags: " + ", ".join(t.name for t in doc.tags))
    if doc.pm_text:
        parts.append(doc.pm_text)
    if doc.dev_text:
        parts.append(doc.dev_text)
    return "\n\n".join(p for p in parts if p)


def build_file_chunk_text(file_summary: str, notable_behavior: str | None) -> str:
    if notable_behavior:
        return f"{file_summary}\n\nNotable: {notable_behavior}"
    return file_summary


def build_method_chunk_text(fqcn: str, method_name: str, source: str) -> str:
    return f"{fqcn}::{method_name}\n\n{source}"
