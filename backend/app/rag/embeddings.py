"""
100% local embeddings via Ollama (`POST /api/embed`) — no dependency on a
cloud API. See docs/rag.md.

Default model: nomic-embed-text (8192-token window, good FR/EN multilingual
behavior — a good fit for infra docs that mix both languages).
"""
from __future__ import annotations

import os

import httpx

DEFAULT_EMBED_MODEL = os.getenv("AEGIS_EMBED_MODEL", "nomic-embed-text")


class EmbeddingError(Exception):
    pass


async def embed_texts(texts: list[str], *, model: str = DEFAULT_EMBED_MODEL, ollama_url: str) -> list[list[float]]:
    """Returns one vector per text, in the same order as `texts`."""
    if not texts:
        return []
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{ollama_url}/api/embed", json={"model": model, "input": texts})
    except httpx.ConnectError as e:
        raise EmbeddingError(f"Ollama unreachable (`{ollama_url}`) for embeddings.") from e

    if resp.status_code != 200:
        raise EmbeddingError(f"Ollama HTTP {resp.status_code} (embeddings): {resp.text[:500]}")

    data = resp.json()
    embeddings = data.get("embeddings")
    if not embeddings or len(embeddings) != len(texts):
        raise EmbeddingError(f"Unexpected embeddings response: {len(embeddings or [])} vectors for {len(texts)} texts.")
    return embeddings


async def embed_query(text: str, *, model: str = DEFAULT_EMBED_MODEL, ollama_url: str) -> list[float]:
    vectors = await embed_texts([text], model=model, ollama_url=ollama_url)
    return vectors[0]
