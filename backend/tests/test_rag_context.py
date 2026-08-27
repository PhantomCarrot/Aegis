from qdrant_client import AsyncQdrantClient

from app.agent.anonymizer import Anonymizer
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


# A JWT-shaped secret: 3 dot-separated parts, each >10 chars, total >100 —
# matches Anonymizer._is_secret_value's JWT heuristic.
FAKE_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
    ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)


async def test_build_context_redacts_secrets_when_anonymizer_given(monkeypatch):
    store = QdrantStore(client=AsyncQdrantClient(location=":memory:"))
    await store.upsert_chunks(
        "demo", "secrets.md",
        [{"text": f"The API token is {FAKE_JWT}.", "heading_path": "Tokens", "chunk_index": 0}],
        [_vec(1)],
    )

    async def fake_embed_query(text, *, model=None, ollama_url):
        return _vec(1)

    monkeypatch.setattr(context_module, "embed_query", fake_embed_query)

    anonymizer = Anonymizer()
    anonymizer.start_turn()
    text, sources = await context_module.build_context(
        TenantConfig(id="demo", name="Demo"), store, "what's the token?", anonymizer=anonymizer
    )

    assert FAKE_JWT not in text
    assert "[SECRET-1]" in text
    # Citations stay legible — only the chunk text is redacted.
    assert sources[0]["source_path"] == "secrets.md"
    assert sources[0]["heading_path"] == "Tokens"


async def test_build_context_skips_redaction_in_confirmed_root_mode(monkeypatch):
    store = QdrantStore(client=AsyncQdrantClient(location=":memory:"))
    await store.upsert_chunks(
        "demo", "secrets.md",
        [{"text": f"The API token is {FAKE_JWT}.", "heading_path": "Tokens", "chunk_index": 0}],
        [_vec(1)],
    )

    async def fake_embed_query(text, *, model=None, ollama_url):
        return _vec(1)

    monkeypatch.setattr(context_module, "embed_query", fake_embed_query)

    anonymizer = Anonymizer()
    anonymizer.start_turn()
    text, _sources = await context_module.build_context(
        TenantConfig(id="demo", name="Demo"), store, "what's the token?",
        anonymizer=anonymizer, safety_mode="__confirmed__",
    )

    assert FAKE_JWT in text
