"""Indexing: chunking + embeddings + Qdrant upsert, orchestrated together. See docs/rag.md."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config.schema import TenantConfig
from app.rag import chunking
from app.rag.embeddings import embed_texts
from app.rag.sparse_embeddings import embed_texts_sparse
from app.rag.store import QdrantStore


async def index_text(
    tenant: TenantConfig, store: QdrantStore, source_path: str, markdown: str
) -> tuple[int, str | None]:
    """
    Chunks, embeds (dense + sparse), and upserts a document. Returns
    (chunks_indexed, generated_at) — generated_at is the ISO UTC timestamp
    stamped on every chunk from this call, or None if there was nothing to
    index (empty markdown).
    """
    chunks = chunking.chunk_markdown(markdown)
    if not chunks:
        return 0, None

    texts = [c.text for c in chunks]
    vectors = await embed_texts(texts, ollama_url=tenant.ollama.url)
    # fastembed/ONNX is synchronous CPU work — offloaded to a thread so it
    # doesn't block the event loop. See app/rag/sparse_embeddings.py.
    sparse_vectors = await asyncio.to_thread(embed_texts_sparse, texts)

    generated_at = datetime.now(timezone.utc).isoformat()
    payload_chunks = [
        {
            "text": c.text,
            "heading_path": c.heading_path,
            "chunk_index": c.chunk_index,
            "generated_at": generated_at,
        }
        for c in chunks
    ]
    # Clean re-indexing: remove any prior chunks from this source first
    # (in case the new document is shorter).
    await store.delete_source(tenant.id, source_path)
    count = await store.upsert_chunks(tenant.id, source_path, payload_chunks, vectors, sparse_vectors)
    return count, generated_at
