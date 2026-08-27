"""
HTTP-level cross-tenant isolation for /api/rag/* — the store-level test
(test_rag_indexing.py::test_tenants_are_isolated_in_different_collections)
proves the collections are separate, but not that a request scoped to
tenant B can never see tenant A's index through the actual endpoints.
Same fixture pattern as test_tenant_header_integration.py.
"""
import pytest
from fastapi.testclient import TestClient
from qdrant_client import AsyncQdrantClient

from app.config import tenants as tenants_module
from app.exec.base import ExecResult
from app.exec.local import LocalExecutor
from app.rag import indexer as indexer_module
from app.rag import store as rag_store_module
from app.rag.store import QdrantStore
from app.stream import ollama_provider

TENANTS_YAML = """
default_tenant: tenant-a
tenants:
  tenant-a:
    name: "Tenant A"
  tenant-b:
    name: "Tenant B"
"""


@pytest.fixture
def client(monkeypatch, tmp_path):
    tenants_file = tmp_path / "tenants.yaml"
    tenants_file.write_text(TENANTS_YAML)

    monkeypatch.setenv("AEGIS_BACKEND_TOKENS", "test-token")
    monkeypatch.setenv("AEGIS_TENANTS_FILE", str(tenants_file))
    monkeypatch.setenv("AEGIS_GLOBAL_CONFIG_FILE", str(tmp_path / "absent-global.yaml"))
    tenants_module.reset_registry()

    rag_store_module._store = QdrantStore(client=AsyncQdrantClient(location=":memory:"))

    async def fake_embed_texts(texts, *, model=None, ollama_url):
        return [[0.1] * 8 for _ in texts]

    monkeypatch.setattr(indexer_module, "embed_texts", fake_embed_texts)

    async def fake_run(self, command, **kwargs):
        return ExecResult(stdout="secret-only-tenant-a-cluster-data", stderr="", returncode=0, command=" ".join(command))

    monkeypatch.setattr(LocalExecutor, "run", fake_run)

    from app.main import app

    yield TestClient(app)

    tenants_module.reset_registry()
    rag_store_module.reset_store()


AUTH = {"Authorization": "Bearer test-token"}


def _generate_for(client, tenant_id: str) -> dict:
    r = client.post("/api/rag/generate", headers={**AUTH, "X-Tenant-Id": tenant_id})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    return r.json()


def test_status_is_isolated_per_tenant(client):
    _generate_for(client, "tenant-a")

    status_a = client.get("/api/rag/status", headers={**AUTH, "X-Tenant-Id": "tenant-a"}).json()
    status_b = client.get("/api/rag/status", headers={**AUTH, "X-Tenant-Id": "tenant-b"}).json()

    assert status_a["ready"] is True
    assert status_a["points_count"] > 0
    assert status_b == {"ready": False, "points_count": 0, "generated_at": None}


def test_documents_are_isolated_per_tenant(client):
    _generate_for(client, "tenant-a")

    docs_a = client.get("/api/rag/documents", headers={**AUTH, "X-Tenant-Id": "tenant-a"}).json()
    docs_b = client.get("/api/rag/documents", headers={**AUTH, "X-Tenant-Id": "tenant-b"}).json()

    assert len(docs_a["documents"]) == 1
    assert docs_b == {"documents": []}


def test_chat_rag_mode_does_not_leak_across_tenants(client, monkeypatch):
    _generate_for(client, "tenant-a")

    from app.rag import context as context_module

    async def fake_embed_query(text, *, model=None, ollama_url):
        return [0.1] * 8

    monkeypatch.setattr(context_module, "embed_query", fake_embed_query)

    captured_system_prompt = {}

    def fake_stream(messages, _tools, _model, ollama_url=None):
        captured_system_prompt["text"] = messages[0]["content"]

        async def gen():
            yield ollama_provider.OllamaTextChunk("ok")

        return gen()

    monkeypatch.setattr(ollama_provider, "stream_chat", fake_stream)

    body = {
        "id": "chat-isolation",
        "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "What's in the cluster?"}]}],
        "mode": "rag",
    }
    with client.stream(
        "POST", "/api/chat", json=body, headers={**AUTH, "X-Tenant-Id": "tenant-b"}
    ) as r:
        "".join(r.iter_text())

    # Tenant B has no index of its own — nothing from tenant A's scraped
    # cluster-overview.md should ever reach tenant B's system prompt.
    assert "secret-only" not in captured_system_prompt.get("text", "")
