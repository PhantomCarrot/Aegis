"""
Integration test for RAG mode in /api/chat: the retrieved context is
injected into the prompt and sources are emitted as `data-ragSources`
before the text. `build_context` (already tested in isolation in
test_rag_context.py) is mocked here — we test the wiring, not the search.
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from qdrant_client import AsyncQdrantClient

from app.config import tenants as tenants_module
from app.rag import context as rag_context_module
from app.rag import store as rag_store_module
from app.rag.store import QdrantStore
from app.routers import chat as chat_module
from app.stream import ollama_provider

TENANTS_YAML = """
default_tenant: demo
tenants:
  demo:
    name: "Demo"
    tools_enabled: [kubectl]
"""


@pytest.fixture
def client(monkeypatch, tmp_path):
    tenants_file = tmp_path / "tenants.yaml"
    tenants_file.write_text(TENANTS_YAML)

    monkeypatch.setenv("AEGIS_BACKEND_TOKENS", "test-token")
    monkeypatch.setenv("AEGIS_TENANTS_FILE", str(tenants_file))
    monkeypatch.setenv("AEGIS_GLOBAL_CONFIG_FILE", str(tmp_path / "absent-global.yaml"))
    tenants_module.reset_registry()

    from app.main import app

    yield TestClient(app)

    tenants_module.reset_registry()
    rag_store_module.reset_store()


AUTH = {"Authorization": "Bearer test-token"}


def _sse_events(raw_text: str) -> list[dict | None]:
    events = []
    for block in raw_text.split("\n\n"):
        if not block.strip():
            continue
        payload = block[len("data: "):]
        events.append(None if payload == "[DONE]" else json.loads(payload))
    return events


def test_rag_mode_injects_context_and_emits_sources(client, monkeypatch):
    captured_system_prompt = {}

    async def fake_build_context(tenant, store, query, anonymizer=None, safety_mode="readonly", top_k=5):
        return (
            "\n\n📚 DOCUMENTATION CONTEXT:\n\n[1] (overview.md)\nThe cluster has 3 namespaces.",
            [{"index": 1, "source_path": "overview.md", "heading_path": "", "score": 0.87}],
        )

    monkeypatch.setattr(chat_module, "build_context", fake_build_context)

    def fake_stream(messages, _tools, _model, ollama_url=None):
        captured_system_prompt["text"] = messages[0]["content"]

        async def gen():
            yield ollama_provider.OllamaTextChunk("The cluster has 3 namespaces according to the docs [1].")

        return gen()

    monkeypatch.setattr(ollama_provider, "stream_chat", fake_stream)

    body = {
        "id": "chat-rag-1",
        "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "How many namespaces?"}]}],
        "mode": "rag",
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        raw = "".join(r.iter_text())

    events = [e for e in _sse_events(raw) if e is not None]
    types = [e["type"] for e in events]
    assert "data-ragSources" in types

    sources_event = next(e for e in events if e["type"] == "data-ragSources")
    assert sources_event["data"]["sources"][0]["source_path"] == "overview.md"

    # The context was properly injected into the system prompt sent to Ollama.
    assert "The cluster has 3 namespaces." in captured_system_prompt["text"]


def test_ops_mode_does_not_call_build_context(client, monkeypatch):
    called = {"n": 0}

    async def fake_build_context(tenant, store, query, anonymizer=None, safety_mode="readonly", top_k=5):
        called["n"] += 1
        return "", []

    monkeypatch.setattr(chat_module, "build_context", fake_build_context)

    def fake_stream(_messages, _tools, _model, ollama_url=None):
        async def gen():
            yield ollama_provider.OllamaTextChunk("ok")

        return gen()

    monkeypatch.setattr(ollama_provider, "stream_chat", fake_stream)

    body = {
        "id": "chat-ops-1",
        "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "Hi"}]}],
        "mode": "ops",
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        "".join(r.iter_text())

    assert called["n"] == 0


def test_rag_mode_falls_back_silently_on_embedding_error(client, monkeypatch):
    from app.rag.embeddings import EmbeddingError

    async def failing_build_context(tenant, store, query, anonymizer=None, safety_mode="readonly", top_k=5):
        raise EmbeddingError("Ollama unreachable")

    monkeypatch.setattr(chat_module, "build_context", failing_build_context)

    def fake_stream(_messages, _tools, _model, ollama_url=None):
        async def gen():
            yield ollama_provider.OllamaTextChunk("ok anyway")

        return gen()

    monkeypatch.setattr(ollama_provider, "stream_chat", fake_stream)

    body = {
        "id": "chat-rag-2",
        "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "Hi"}]}],
        "mode": "rag",
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        assert r.status_code == 200
        raw = "".join(r.iter_text())

    events = [e for e in _sse_events(raw) if e is not None]
    types = [e["type"] for e in events]
    assert "data-ragSources" not in types
    assert "text-delta" in types  # the conversation continues anyway


# A JWT-shaped secret — matches Anonymizer._is_secret_value's JWT heuristic.
FAKE_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0"
    ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)


def test_rag_mode_redacts_secrets_from_indexed_chunks_before_the_prompt(client, monkeypatch):
    """
    End-to-end with the REAL build_context (not mocked) against an in-memory
    store holding a chunk with a secret — the system prompt Ollama actually
    receives must never contain the raw secret. See docs/security-model.md.
    """
    store = QdrantStore(client=AsyncQdrantClient(location=":memory:"))
    monkeypatch.setattr(chat_module, "get_store", lambda: store)

    asyncio.run(
        store.upsert_chunks(
            "demo", "secrets.md",
            [{"text": f"The API token is {FAKE_JWT}.", "heading_path": "Tokens", "chunk_index": 0}],
            [[0.1] * 8],
        )
    )

    async def fake_embed_query(text, *, model=None, ollama_url):
        return [0.1] * 8

    monkeypatch.setattr(rag_context_module, "embed_query", fake_embed_query)

    captured_system_prompt = {}

    def fake_stream(messages, _tools, _model, ollama_url=None):
        captured_system_prompt["text"] = messages[0]["content"]

        async def gen():
            yield ollama_provider.OllamaTextChunk("Here's the info [1].")

        return gen()

    monkeypatch.setattr(ollama_provider, "stream_chat", fake_stream)

    body = {
        "id": "chat-rag-secret",
        "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "What's the API token?"}]}],
        "mode": "rag",
    }
    with client.stream("POST", "/api/chat", json=body, headers=AUTH) as r:
        "".join(r.iter_text())

    assert FAKE_JWT not in captured_system_prompt["text"]
    assert "[SECRET-1]" in captured_system_prompt["text"]
