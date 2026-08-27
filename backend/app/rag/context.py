"""
RAG context injected into the chat's system prompt in RAG mode: hybrid
(dense + sparse, RRF-fused) search over the indexed docs + source
citations. See docs/rag.md.
"""
from __future__ import annotations

import asyncio

from app.agent.anonymizer import Anonymizer
from app.config.schema import TenantConfig
from app.logging_config import get_audit_logger
from app.rag.embeddings import embed_query
from app.rag.sparse_embeddings import embed_query_sparse
from app.rag.store import QdrantStore

DEFAULT_TOP_K = 5

# Fused RRF scores live on a very different scale than raw cosine similarity
# (Qdrant's default RRF constant k=60 caps a hit found at rank 0 in both
# dense and sparse at ~0.033) — this is a conservative starting cutoff for
# obviously-irrelevant long-tail hits, not a tuned value. See docs/rag.md.
SCORE_THRESHOLD = 0.01

_audit = get_audit_logger()


async def build_context(
    tenant: TenantConfig,
    store: QdrantStore,
    query: str,
    anonymizer: Anonymizer | None = None,
    safety_mode: str = "readonly",
    top_k: int = DEFAULT_TOP_K,
) -> tuple[str, list[dict]]:
    """
    Returns (text_to_inject_into_prompt, sources). `sources` is a list of
    {index, source_path, heading_path, score} meant for displaying
    citations on the frontend (the `data-ragSources` part). Returns ("",
    []) if the index is empty or the search finds nothing.

    `anonymizer`, when given, redacts secret-looking tokens out of the
    indexed text before it's injected into the prompt — the same per-turn
    instance already used for tool-result redaction, so a secret seen
    earlier this turn gets the same placeholder here (see
    docs/security-model.md). Never applied to `source_path`/`heading_path`
    (citations must stay legible) — only to the retrieved chunk text.
    """
    query_vector = await embed_query(query, ollama_url=tenant.ollama.url)
    # fastembed/ONNX sparse embedding is synchronous CPU work — offloaded to
    # a thread, same as app/rag/indexer.py.
    query_sparse = await asyncio.to_thread(embed_query_sparse, query)
    hits = await store.search(
        tenant.id, query_vector, query_sparse, top_k=top_k, score_threshold=SCORE_THRESHOLD
    )
    if not hits:
        _audit.info("rag_search tenant=%s hits=0 top_score=None query_chars=%d", tenant.id, len(query))
        return "", []

    _audit.info(
        "rag_search tenant=%s hits=%d top_score=%.4f query_chars=%d",
        tenant.id, len(hits), hits[0].get("score", 0.0), len(query),
    )

    context_parts = []
    sources = []
    for i, hit in enumerate(hits, start=1):
        text = hit.get("text", "")
        if anonymizer is not None:
            text = anonymizer.anonymize_text(text, safety_mode)
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
