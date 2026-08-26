"""
Integration test for RAG mode in /api/chat: the retrieved context is
injected into the prompt and sources are emitted as `data-ragSources`
before the text. `build_context` (already tested in isolation in
test_rag_context.py) is mocked here — we test the wiring, not the search.
"""
import json

import pytest
from fastapi.testclient import TestClient

from app.config import tenants as tenants_module
from app.rag import store as rag_store_module
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

    async def fake_build_context(tenant, store, query, top_k=5):
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

    async def fake_build_context(tenant, store, query, top_k=5):
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

    async def failing_build_context(tenant, store, query, top_k=5):
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
