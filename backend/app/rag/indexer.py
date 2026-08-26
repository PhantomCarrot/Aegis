"""Indexing: chunking + embeddings + Qdrant upsert, orchestrated together. See docs/rag.md."""
from __future__ import annotations

from app.config.schema import TenantConfig
from app.rag import chunking
from app.rag.embeddings import embed_texts
from app.rag.store import QdrantStore


async def index_text(tenant: TenantConfig, store: QdrantStore, source_path: str, markdown: str) -> int:
    """Chunks, embeds, and upserts a document — returns the number of chunks indexed."""
    chunks = chunking.chunk_markdown(markdown)
    if not chunks:
        return 0

    vectors = await embed_texts([c.text for c in chunks], ollama_url=tenant.ollama.url)

    payload_chunks = [
        {"text": c.text, "heading_path": c.heading_path, "chunk_index": c.chunk_index}
        for c in chunks
    ]
    # Clean re-indexing: remove any prior chunks from this source first
    # (in case the new document is shorter).
    await store.delete_source(tenant.id, source_path)
    return await store.upsert_chunks(tenant.id, source_path, payload_chunks, vectors)
