"""
Tests for the Qdrant store + the indexer, with an in-memory Qdrant client
(`AsyncQdrantClient(location=":memory:")`) and fake embeddings — no
dependency on a real Qdrant/Ollama.
"""
import pytest
from qdrant_client import AsyncQdrantClient

from app.config.schema import TenantConfig
from app.rag import indexer as indexer_module
from app.rag import store as store_module
from app.rag.store import QdrantStore, collection_name

VECTOR_SIZE = 8


def _fake_vector(seed: int) -> list[float]:
    return [float((seed + i) % 7) / 10 for i in range(VECTOR_SIZE)]


@pytest.fixture
def store():
    return QdrantStore(client=AsyncQdrantClient(location=":memory:"))


def _tenant(tenant_id: str = "demo") -> TenantConfig:
    return TenantConfig(id=tenant_id, name="Demo")


# ─── QdrantStore ───────────────────────────────────────────────────────────

async def test_status_reports_not_ready_when_no_collection(store):
    status = await store.status("demo")
    assert status == {"ready": False, "points_count": 0}


async def test_upsert_creates_collection_and_status_reflects_it(store):
    n = await store.upsert_chunks(
        "demo", "doc.md",
        [{"text": "hello", "heading_path": "", "chunk_index": 0}],
        [_fake_vector(1)],
    )
    assert n == 1
    status = await store.status("demo")
    assert status == {"ready": True, "points_count": 1}


async def test_reindexing_same_source_overwrites_not_duplicates(store):
    await store.upsert_chunks(
        "demo", "doc.md",
        [{"text": "v1", "heading_path": "", "chunk_index": 0}],
        [_fake_vector(1)],
    )
    await store.upsert_chunks(
        "demo", "doc.md",
        [{"text": "v2", "heading_path": "", "chunk_index": 0}],
        [_fake_vector(1)],
    )
    status = await store.status("demo")
    assert status["points_count"] == 1  # not 2 — same deterministic ID


async def test_delete_source_removes_only_that_sources_chunks(store):
    await store.upsert_chunks(
        "demo", "a.md", [{"text": "a", "heading_path": "", "chunk_index": 0}], [_fake_vector(1)],
    )
    await store.upsert_chunks(
        "demo", "b.md", [{"text": "b", "heading_path": "", "chunk_index": 0}], [_fake_vector(2)],
    )
    await store.delete_source("demo", "a.md")
    status = await store.status("demo")
    assert status["points_count"] == 1


async def test_tenants_are_isolated_in_different_collections(store):
    await store.upsert_chunks(
        "tenant-a", "doc.md", [{"text": "a", "heading_path": "", "chunk_index": 0}], [_fake_vector(1)],
    )
    assert (await store.status("tenant-a"))["ready"] is True
    assert (await store.status("tenant-b"))["ready"] is False
    assert collection_name("tenant-a") != collection_name("tenant-b")


async def test_search_returns_scored_payloads(store):
    await store.upsert_chunks(
        "demo", "doc.md",
        [{"text": "chunk one", "heading_path": "H1", "chunk_index": 0}],
        [_fake_vector(1)],
    )
    hits = await store.search("demo", _fake_vector(1), top_k=3)
    assert len(hits) == 1
    assert hits[0]["text"] == "chunk one"
    assert hits[0]["source_path"] == "doc.md"
    assert "score" in hits[0]


async def test_search_on_missing_collection_returns_empty(store):
    assert await store.search("does-not-exist", _fake_vector(1)) == []


async def test_list_chunks_returns_all_payloads(store):
    await store.upsert_chunks(
        "demo", "a.md",
        [
            {"text": "chunk 0", "heading_path": "", "chunk_index": 0},
            {"text": "chunk 1", "heading_path": "", "chunk_index": 1},
        ],
        [_fake_vector(1), _fake_vector(2)],
    )
    await store.upsert_chunks(
        "demo", "b.md", [{"text": "other doc", "heading_path": "", "chunk_index": 0}], [_fake_vector(3)],
    )

    chunks = await store.list_chunks("demo")
    assert len(chunks) == 3
    assert {c["source_path"] for c in chunks} == {"a.md", "b.md"}


async def test_list_chunks_on_missing_collection_returns_empty(store):
    assert await store.list_chunks("does-not-exist") == []


def test_store_passes_url_and_api_key_to_client(monkeypatch):
    """QDRANT_URL isn't limited to the local docker-compose instance — a
    remote/managed Qdrant (e.g. Qdrant Cloud) needs the api_key too."""
    captured: dict = {}

    class FakeAsyncQdrantClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(store_module, "AsyncQdrantClient", FakeAsyncQdrantClient)

    store_module.QdrantStore(url="https://my-cluster.qdrant.io", api_key="secret-key")

    assert captured["url"] == "https://my-cluster.qdrant.io"
    assert captured["api_key"] == "secret-key"


def test_store_defaults_api_key_to_env_var(monkeypatch):
    monkeypatch.setattr(store_module, "DEFAULT_QDRANT_API_KEY", "from-env")
    captured: dict = {}

    class FakeAsyncQdrantClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(store_module, "AsyncQdrantClient", FakeAsyncQdrantClient)

    store_module.QdrantStore(url="http://localhost:6333")

    assert captured["api_key"] == "from-env"


# ─── Indexer ───────────────────────────────────────────────────────────────

async def test_index_text_chunks_embeds_and_upserts(store, monkeypatch):
    async def fake_embed_texts(texts, *, model=None, ollama_url):
        return [_fake_vector(i) for i in range(len(texts))]

    monkeypatch.setattr(indexer_module, "embed_texts", fake_embed_texts)

    md = "# Overview\n\nIntro.\n\n## Pods\n\nList of pods.\n"
    n = await indexer_module.index_text(_tenant(), store, "overview.md", md)

    assert n == 2  # two sections → two chunks
    status = await store.status("demo")
    assert status["points_count"] == 2


async def test_index_text_empty_document_indexes_nothing(store, monkeypatch):
    called = {"n": 0}

    async def fake_embed_texts(texts, *, model=None, ollama_url):
        called["n"] += 1
        return []

    monkeypatch.setattr(indexer_module, "embed_texts", fake_embed_texts)

    n = await indexer_module.index_text(_tenant(), store, "empty.md", "")
    assert n == 0
    assert called["n"] == 0  # never called — short-circuits before embedding
