"""Integration test for GET /api/tools — tool introspection (see docs/tools.md)."""
import pytest
from fastapi.testclient import TestClient

from app.agent.tools import availability as availability_module
from app.config import tenants as tenants_module
from app.exec.base import ExecResult
from app.exec.local import LocalExecutor

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
    availability_module.reset_cache()

    # GET /api/tools now probes real binaries via LocalExecutor — without
    # this, every test here would depend on what's actually installed on
    # whatever machine runs the suite. Default: every probe succeeds.
    async def fake_run(self, command, **kwargs):
        return ExecResult(stdout="/usr/bin/x", stderr="", returncode=0, command=str(command))

    monkeypatch.setattr(LocalExecutor, "run", fake_run)

    from app.main import app

    yield TestClient(app)

    tenants_module.reset_registry()
    availability_module.reset_cache()


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


def test_list_tools_reports_binary_available_when_probe_succeeds(client):
    r = client.get("/api/tools", headers={**AUTH, "X-Tenant-Id": "demo"})
    by_name = {t["name"]: t for t in r.json()["tools"]}
    assert by_name["kubectl_get"]["available"] is True


def test_list_tools_reports_binary_unavailable_when_probe_fails(client, monkeypatch):
    async def fake_run_missing(self, command, **kwargs):
        return ExecResult(stdout="", stderr="", returncode=1, command=str(command))

    monkeypatch.setattr(LocalExecutor, "run", fake_run_missing)

    r = client.get("/api/tools", headers={**AUTH, "X-Tenant-Id": "demo"})
    by_name = {t["name"]: t for t in r.json()["tools"]}
    assert by_name["kubectl_get"]["available"] is False
    # argocd tools actually run through kubectl (see agent/tools/argocd.py)
    # — same missing binary should mark them unavailable too.
    assert by_name["argocd_app_list"]["available"] is False


def test_run_command_always_available_and_never_probed(client, monkeypatch):
    calls = []

    async def fake_run_tracking(self, command, **kwargs):
        calls.append(str(command))
        return ExecResult(stdout="", stderr="", returncode=1, command=str(command))

    monkeypatch.setattr(LocalExecutor, "run", fake_run_tracking)

    r = client.get("/api/tools", headers={**AUTH, "X-Tenant-Id": "demo"})
    by_name = {t["name"]: t for t in r.json()["tools"]}
    assert by_name["run_command"]["available"] is True
    # GET /api/tools reports every known tool, not just this tenant's
    # enabled ones — kubectl_get/describe/logs and argocd_app_list/status
    # all share "kubectl" (cached after the first probe), cloud_cli probes
    # "az" (the default provider), and run_command has nothing to probe:
    # exactly two calls total, never "run_command" itself.
    assert sorted(calls) == ["command -v az", "command -v kubectl"]
