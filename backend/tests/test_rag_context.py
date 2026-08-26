from qdrant_client import AsyncQdrantClient

from app.config.schema import TenantConfig
from app.rag import context as context_module
from app.rag.store import QdrantStore

VECTOR_SIZE = 8


def _vec(seed: int) -> list[float]:
    return [float((seed + i) % 7) / 10 for i in range(VECTOR_SIZE)]


async def test_build_context_returns_empty_when_index_is_empty(monkeypatch):
    store = QdrantStore(client=AsyncQdrantClient(location=":memory:"))

    async def fake_embed_query(text, *, model=None, ollama_url):
        return _vec(1)

    monkeypatch.setattr(context_module, "embed_query", fake_embed_query)

    text, sources = await context_module.build_context(
        TenantConfig(id="demo", name="Demo"), store, "some questions?"
    )
    assert text == ""
    assert sources == []


async def test_build_context_formats_citations_and_sources(monkeypatch):
    store = QdrantStore(client=AsyncQdrantClient(location=":memory:"))
    await store.upsert_chunks(
        "demo", "overview.md",
        [{"text": "The demo namespace has 3 pods.", "heading_path": "Pods", "chunk_index": 0}],
        [_vec(1)],
    )

    async def fake_embed_query(text, *, model=None, ollama_url):
        return _vec(1)

    monkeypatch.setattr(context_module, "embed_query", fake_embed_query)

    text, sources = await context_module.build_context(
        TenantConfig(id="demo", name="Demo"), store, "how many pods?"
    )

    assert "[1]" in text
    assert "The demo namespace has 3 pods." in text
    assert sources == [{"index": 1, "source_path": "overview.md", "heading_path": "Pods", "score": sources[0]["score"]}]
