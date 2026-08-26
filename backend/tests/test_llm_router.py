"""Integration test for GET /api/llm/models — provider-aware model discovery
(Ollama, LM Studio, AirLLM). See docs/llm-providers.md."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import tenants as tenants_module
from app.routers import llm as llm_router_module

TENANTS_YAML = """
default_tenant: ollama-tenant
tenants:
  ollama-tenant:
    name: "Ollama"
  lmstudio-tenant:
    name: "LM Studio"
    llm:
      provider: lmstudio
      lmstudio:
        url: "http://localhost:1234"
  airllm-tenant:
    name: "AirLLM"
    llm:
      provider: airllm
      airllm:
        model: "meta-llama/Llama-3.2-3B-Instruct"
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


AUTH = {"Authorization": "Bearer test-token"}


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload_by_path: dict[str, dict], *, timeout=None):
        self._payload_by_path = payload_by_path

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url: str):
        for path, payload in self._payload_by_path.items():
            if url.endswith(path):
                return _FakeResponse(200, payload)
        raise httpx.ConnectError("connection refused")


def test_ollama_provider_lists_models(client, monkeypatch):
    payload = {"/api/tags": {"models": [{"name": "qwen3.6:35b"}, {"name": "devstral:latest"}]}}
    monkeypatch.setattr(llm_router_module.httpx, "AsyncClient", lambda timeout=None: _FakeAsyncClient(payload))

    r = client.get("/api/llm/models", headers={**AUTH, "X-Tenant-Id": "ollama-tenant"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "ollama"
    assert body["models"] == ["devstral:latest", "qwen3.6:35b"]


def test_lmstudio_provider_lists_models(client, monkeypatch):
    payload = {"/v1/models": {"data": [{"id": "qwen2.5-7b-instruct"}, {"id": "llama-3.2-3b"}]}}
    monkeypatch.setattr(llm_router_module.httpx, "AsyncClient", lambda timeout=None: _FakeAsyncClient(payload))

    r = client.get("/api/llm/models", headers={**AUTH, "X-Tenant-Id": "lmstudio-tenant"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "lmstudio"
    assert body["models"] == ["llama-3.2-3b", "qwen2.5-7b-instruct"]
    assert body["lmstudio_url"] == "http://localhost:1234"


def test_lmstudio_provider_reports_error_without_crashing_when_unreachable(client, monkeypatch):
    monkeypatch.setattr(llm_router_module.httpx, "AsyncClient", lambda timeout=None: _FakeAsyncClient({}))

    r = client.get("/api/llm/models", headers={**AUTH, "X-Tenant-Id": "lmstudio-tenant"})
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == []
    assert "error" in body


def test_airllm_provider_returns_fixed_configured_model(client):
    """AirLLM has no live model discovery — its model is a fixed part of the tenant config."""
    r = client.get("/api/llm/models", headers={**AUTH, "X-Tenant-Id": "airllm-tenant"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "airllm"
    assert body["models"] == ["meta-llama/Llama-3.2-3B-Instruct"]


def test_requires_auth(client):
    r = client.get("/api/llm/models")
    assert r.status_code == 401
