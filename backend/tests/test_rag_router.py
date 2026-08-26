"""Integration test for /api/rag/generate and /api/rag/status."""
import pytest
from fastapi.testclient import TestClient
from qdrant_client import AsyncQdrantClient

from app.config import tenants as tenants_module
from app.exec.base import ExecResult
from app.exec.local import LocalExecutor
from app.rag import indexer as indexer_module
from app.rag import store as rag_store_module
from app.rag.store import QdrantStore

TENANTS_YAML = """
default_tenant: demo
tenants:
  demo:
    name: "Demo"
"""


@pytest.fixture
def client(monkeypatch, tmp_path):
    tenants_file = tmp_path / "tenants.yaml"
    tenants_file.write_text(TENANTS_YAML)

    monkeypatch.setenv("AEGIS_BACKEND_TOKENS", "test-token")
    monkeypatch.setenv("AEGIS_TENANTS_FILE", str(tenants_file))
    monkeypatch.setenv("AEGIS_GLOBAL_CONFIG_FILE", str(tmp_path / "absent-global.yaml"))
    tenants_module.reset_registry()

    # In-memory store injected into the singleton — no real Qdrant in tests.
    rag_store_module._store = QdrantStore(client=AsyncQdrantClient(location=":memory:"))

    from app.main import app

    yield TestClient(app)

    tenants_module.reset_registry()
    rag_store_module.reset_store()


AUTH = {"Authorization": "Bearer test-token"}


async def _fake_embed_texts(texts, *, model=None, ollama_url):
    return [[0.1] * 8 for _ in texts]


def test_status_before_any_generation(client):
    r = client.get("/api/rag/status", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"ready": False, "points_count": 0}


def test_generate_scrapes_indexes_and_updates_status(client, monkeypatch):
    monkeypatch.setattr(indexer_module, "embed_texts", _fake_embed_texts)

    async def fake_run(self, command, **kwargs):
        return ExecResult(stdout="fake output", stderr="", returncode=0, command=" ".join(command))

    monkeypatch.setattr(LocalExecutor, "run", fake_run)

    r = client.post("/api/rag/generate", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["chunks_indexed"] >= 1

    status = client.get("/api/rag/status", headers=AUTH).json()
    assert status["ready"] is True
    assert status["points_count"] == body["chunks_indexed"]


def test_generate_reports_embedding_failure_without_crashing(client, monkeypatch):
    from app.rag.embeddings import EmbeddingError

    async def failing_embed(texts, *, model=None, ollama_url):
        raise EmbeddingError("Ollama inaccessible")

    monkeypatch.setattr(indexer_module, "embed_texts", failing_embed)

    async def fake_run(self, command, **kwargs):
        return ExecResult(stdout="fake output", stderr="", returncode=0, command=" ".join(command))

    monkeypatch.setattr(LocalExecutor, "run", fake_run)

    r = client.post("/api/rag/generate", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_documents_empty_before_generation(client):
    r = client.get("/api/rag/documents", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"documents": []}


def test_documents_lists_indexed_content_after_generation(client, monkeypatch):
    monkeypatch.setattr(indexer_module, "embed_texts", _fake_embed_texts)

    async def fake_run(self, command, **kwargs):
        return ExecResult(stdout="fake output", stderr="", returncode=0, command=" ".join(command))

    monkeypatch.setattr(LocalExecutor, "run", fake_run)

    client.post("/api/rag/generate", headers=AUTH)

    r = client.get("/api/rag/documents", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert len(body["documents"]) == 1
    doc = body["documents"][0]
    assert doc["source_path"] == "cluster-overview.md"
    assert doc["chunk_count"] == len(doc["chunks"])
    # chunks are sorted by chunk_index
    assert [c["chunk_index"] for c in doc["chunks"]] == sorted(c["chunk_index"] for c in doc["chunks"])
    assert all("text" in c for c in doc["chunks"])


def test_tenant_config_exposes_exec_target_and_ollama_url(client):
    r = client.get("/api/tenants/config", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "demo"
    assert body["exec"] == {"mode": "local", "target": "local"}
    assert body["ollama"]["url"]  # present, default or overridden value
    assert "domain_notes" in body
