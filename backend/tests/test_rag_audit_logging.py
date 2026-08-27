"""
Verifies rag_search/rag_generate are traced in the audit logger
(app.logging_config.AUDIT_LOGGER_NAME), same pattern as
test_audit_logging.py (guardrails). Doesn't test the exact format, just
that the event is emitted with the right outcome. See docs/rag.md.
"""
import logging

import pytest
from fastapi.testclient import TestClient
from qdrant_client import AsyncQdrantClient

from app.config import tenants as tenants_module
from app.config.schema import TenantConfig
from app.exec.base import ExecResult
from app.exec.local import LocalExecutor
from app.logging_config import AUDIT_LOGGER_NAME
from app.rag import context as context_module
from app.rag import indexer as indexer_module
from app.rag import store as rag_store_module
from app.rag.store import QdrantStore

VECTOR_SIZE = 8


def _vec(seed: int) -> list[float]:
    return [float((seed + i) % 7) / 10 for i in range(VECTOR_SIZE)]


async def test_build_context_logs_rag_search_with_a_hit(monkeypatch, caplog):
    store = QdrantStore(client=AsyncQdrantClient(location=":memory:"))
    await store.upsert_chunks(
        "demo", "overview.md",
        [{"text": "The demo namespace has 3 pods.", "heading_path": "Pods", "chunk_index": 0}],
        [_vec(1)],
    )

    async def fake_embed_query(text, *, model=None, ollama_url):
        return _vec(1)

    monkeypatch.setattr(context_module, "embed_query", fake_embed_query)
    monkeypatch.setattr(context_module, "SCORE_THRESHOLD", None)

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER_NAME):
        await context_module.build_context(TenantConfig(id="demo", name="Demo"), store, "how many pods?")

    records = [r for r in caplog.records if r.name == AUDIT_LOGGER_NAME]
    assert any("rag_search" in r.message and "tenant=demo" in r.message and "hits=1" in r.message for r in records)


async def test_build_context_logs_rag_search_with_zero_hits(monkeypatch, caplog):
    store = QdrantStore(client=AsyncQdrantClient(location=":memory:"))

    async def fake_embed_query(text, *, model=None, ollama_url):
        return _vec(1)

    monkeypatch.setattr(context_module, "embed_query", fake_embed_query)

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER_NAME):
        await context_module.build_context(TenantConfig(id="demo", name="Demo"), store, "anything?")

    records = [r for r in caplog.records if r.name == AUDIT_LOGGER_NAME]
    assert any("rag_search" in r.message and "hits=0" in r.message for r in records)


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

    rag_store_module._store = QdrantStore(client=AsyncQdrantClient(location=":memory:"))

    from app.main import app

    yield TestClient(app)

    tenants_module.reset_registry()
    rag_store_module.reset_store()


AUTH = {"Authorization": "Bearer test-token"}


def test_generate_logs_rag_generate_on_success(client, monkeypatch, caplog):
    async def fake_embed_texts(texts, *, model=None, ollama_url):
        return [[0.1] * 8 for _ in texts]

    monkeypatch.setattr(indexer_module, "embed_texts", fake_embed_texts)

    async def fake_run(self, command, **kwargs):
        return ExecResult(stdout="fake output", stderr="", returncode=0, command=" ".join(command))

    monkeypatch.setattr(LocalExecutor, "run", fake_run)

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER_NAME):
        r = client.post("/api/rag/generate", headers=AUTH)
    assert r.status_code == 200

    records = [rec for rec in caplog.records if rec.name == AUDIT_LOGGER_NAME]
    assert any(
        "rag_generate" in rec.message and "tenant=demo" in rec.message and "ok=True" in rec.message
        for rec in records
    )


def test_generate_logs_rag_generate_on_embedding_failure(client, monkeypatch, caplog):
    from app.rag.embeddings import EmbeddingError

    async def failing_embed(texts, *, model=None, ollama_url):
        raise EmbeddingError("Ollama inaccessible")

    monkeypatch.setattr(indexer_module, "embed_texts", failing_embed)

    async def fake_run(self, command, **kwargs):
        return ExecResult(stdout="fake output", stderr="", returncode=0, command=" ".join(command))

    monkeypatch.setattr(LocalExecutor, "run", fake_run)

    with caplog.at_level(logging.INFO, logger=AUDIT_LOGGER_NAME):
        r = client.post("/api/rag/generate", headers=AUTH)
    assert r.status_code == 200

    records = [rec for rec in caplog.records if rec.name == AUDIT_LOGGER_NAME]
    assert any(
        "rag_generate" in rec.message and "ok=False" in rec.message
        for rec in records
    )
