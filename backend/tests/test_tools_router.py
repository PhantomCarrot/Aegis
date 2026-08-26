"""Integration test for GET /api/tools — tool introspection (see docs/tools.md)."""
import pytest
from fastapi.testclient import TestClient

from app.config import tenants as tenants_module

TENANTS_YAML = """
default_tenant: demo
tenants:
  demo:
    name: "Demo"
    tools_enabled: [kubectl, run_command]
  restricted:
    name: "Restricted"
    tools_enabled: [kubectl_get]
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


def test_list_tools_includes_all_known_tools_with_enabled_flag(client):
    r = client.get("/api/tools", headers={**AUTH, "X-Tenant-Id": "demo"})
    assert r.status_code == 200
    body = r.json()
    by_name = {t["name"]: t for t in body["tools"]}

    assert "kubectl_get" in by_name
    assert "run_command" in by_name
    assert "cloud_cli" in by_name  # present even if not enabled — enabled=False

    assert by_name["kubectl_get"]["enabled"] is True
    assert by_name["run_command"]["enabled"] is True
    assert by_name["cloud_cli"]["enabled"] is False


def test_list_tools_exposes_exact_ollama_schema(client):
    r = client.get("/api/tools", headers={**AUTH, "X-Tenant-Id": "demo"})
    by_name = {t["name"]: t for t in r.json()["tools"]}
    schema = by_name["kubectl_get"]["schema"]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "kubectl_get"
    assert "parameters" in schema["function"]


def test_run_command_is_guarded_kubectl_get_is_not(client):
    r = client.get("/api/tools", headers={**AUTH, "X-Tenant-Id": "demo"})
    by_name = {t["name"]: t for t in r.json()["tools"]}
    assert by_name["run_command"]["guarded"] is True
    assert by_name["kubectl_get"]["guarded"] is False


def test_list_tools_respects_per_tenant_restriction(client):
    r = client.get("/api/tools", headers={**AUTH, "X-Tenant-Id": "restricted"})
    by_name = {t["name"]: t for t in r.json()["tools"]}
    assert by_name["kubectl_get"]["enabled"] is True
    assert by_name["kubectl_describe"]["enabled"] is False
    assert by_name["run_command"]["enabled"] is False


def test_list_tools_requires_auth(client):
    r = client.get("/api/tools")
    assert r.status_code == 401
