"""
RAG context injected into the chat's system prompt in RAG mode: semantic
search over the indexed docs + source citations. See docs/rag.md.
"""
from __future__ import annotations

from app.config.schema import TenantConfig
from app.rag.embeddings import embed_query
from app.rag.store import QdrantStore

DEFAULT_TOP_K = 5


async def build_context(
    tenant: TenantConfig, store: QdrantStore, query: str, top_k: int = DEFAULT_TOP_K
) -> tuple[str, list[dict]]:
    """
    Returns (text_to_inject_into_prompt, sources). `sources` is a list of
    {index, source_path, heading_path, score} meant for displaying
    citations on the frontend (the `data-ragSources` part). Returns ("",
    []) if the index is empty or the search finds nothing.
    """
    query_vector = await embed_query(query, ollama_url=tenant.ollama.url)
    hits = await store.search(tenant.id, query_vector, top_k=top_k)
    if not hits:
        return "", []

    context_parts = []
    sources = []
    for i, hit in enumerate(hits, start=1):
        text = hit.get("text", "")
        heading = hit.get("heading_path", "")
        source_path = hit.get("source_path", "?")
        label = f"{source_path}{' — ' + heading if heading else ''}"
        context_parts.append(f"[{i}] ({label})\n{text}")
        sources.append({
            "index": i,
            "source_path": source_path,
            "heading_path": heading,
            "score": hit.get("score", 0.0),
        })

    context_text = (
        "\n\n📚 DOCUMENTATION CONTEXT (indexed infra excerpts — cite the "
        "relevant sources by their bracketed number, e.g. [1]):\n\n"
        + "\n\n---\n\n".join(context_parts)
    )
    return context_text, sources
