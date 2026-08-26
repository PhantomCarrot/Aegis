"""
End-to-end integration test: /api/ping resolves the active tenant from the
X-Tenant-Id header (no global server-side state — see docs/multi-tenant.md).
"""
import pytest
from fastapi.testclient import TestClient

from app.config import tenants as tenants_module

TENANTS_YAML = """
default_tenant: demo
tenants:
  demo:
    name: "Demo"
  acme-corp:
    name: "Acme Corp"
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


def test_ping_defaults_to_default_tenant(client):
    r = client.get("/api/ping", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["tenant"] == {"id": "demo", "name": "Demo"}


def test_ping_switches_tenant_via_header(client):
    r = client.get("/api/ping", headers={**AUTH, "X-Tenant-Id": "acme-corp"})
    assert r.status_code == 200
    assert r.json()["tenant"] == {"id": "acme-corp", "name": "Acme Corp"}


def test_ping_rejects_unknown_tenant(client):
    r = client.get("/api/ping", headers={**AUTH, "X-Tenant-Id": "does-not-exist"})
    assert r.status_code == 404


def test_tenants_endpoint_lists_both(client):
    r = client.get("/api/tenants", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["default_tenant"] == "demo"
    assert {t["id"] for t in body["tenants"]} == {"demo", "acme-corp"}
