"""
The tenant-administration endpoints on top of app/config/writer.py:
POST /api/tenants, GET/PUT/DELETE /api/tenants/{id}, PUT /api/tenants/default.
See test_tenant_header_integration.py for the fixture pattern this follows.
"""
import pytest
from fastapi.testclient import TestClient

from app.config import tenants as tenants_module

TENANTS_YAML = """default_tenant: demo
tenants:
  demo:
    name: "Demo"
    exec:
      mode: ssh
      ssh:
        host: "10.0.0.5"
        user: "opsagent"
        key_path: "~/.ssh/aegis_demo"
        certificate_path: "~/.ssh/aegis_demo-cert.pub"
        known_hosts_path: "~/.ssh/aegis_demo_known_hosts"
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


# ── create ──────────────────────────────────────────────────────────────


def test_create_then_list_reflects_it_on_the_very_next_request(client):
    r = client.post(
        "/api/tenants",
        headers=AUTH,
        json={"id": "verify-test", "name": "Verify Test", "tools_enabled": ["run_command"]},
    )
    assert r.status_code == 201
    assert r.json()["id"] == "verify-test"

    # No restart, no manual reload — hot-reload picks it up on the next call.
    listed = client.get("/api/tenants", headers=AUTH).json()
    assert "verify-test" in {t["id"] for t in listed["tenants"]}


def test_create_duplicate_id_is_409(client):
    r = client.post("/api/tenants", headers=AUTH, json={"id": "demo", "name": "Dup"})
    assert r.status_code == 409


def test_create_invalid_body_is_422(client):
    # exec.mode == "ssh" without an ssh block — caught by LLMConfig/ExecConfig's
    # own cross-field validators at the HTTP body layer, before writer.py runs.
    r = client.post(
        "/api/tenants",
        headers=AUTH,
        json={"id": "bad", "name": "Bad", "exec": {"mode": "ssh"}},
    )
    assert r.status_code == 422


def test_create_requires_auth(client):
    r = client.post("/api/tenants", json={"id": "x", "name": "X"})
    assert r.status_code == 401


# ── read ────────────────────────────────────────────────────────────────


def test_full_config_is_unredacted_unlike_the_active_tenant_summary(client):
    full = client.get("/api/tenants/demo", headers=AUTH).json()
    assert full["exec"]["ssh"]["key_path"] == "~/.ssh/aegis_demo"
    assert full["exec"]["ssh"]["certificate_path"] == "~/.ssh/aegis_demo-cert.pub"

    summary = client.get(
        "/api/tenants/config", headers={**AUTH, "X-Tenant-Id": "demo"}
    ).json()
    assert "key_path" not in summary["exec"]
    assert "certificate_path" not in summary["exec"]


def test_full_config_unknown_tenant_is_404(client):
    r = client.get("/api/tenants/does-not-exist", headers=AUTH)
    assert r.status_code == 404


# ── update ──────────────────────────────────────────────────────────────


def test_update_then_get_reflects_the_change(client):
    r = client.put(
        "/api/tenants/acme-corp",
        headers=AUTH,
        json={"name": "Acme Corp (renamed)", "domain_notes": "updated"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Acme Corp (renamed)"

    refetched = client.get("/api/tenants/acme-corp", headers=AUTH).json()
    assert refetched["name"] == "Acme Corp (renamed)"
    assert refetched["domain_notes"] == "updated"


def test_update_round_trips_terraform_dir_and_cloud_provider(client):
    """
    Regression test for a real bug caught while planning this change:
    TenantWriteRequest didn't declare these fields, and update_tenant()
    replaces the tenant's YAML node wholesale (body.model_dump(exclude_none=True))
    — so a hand-set terraform_dir/cloud_provider would silently vanish on
    the very next save through the admin UI. See app/routers/tenants.py.
    """
    r = client.put(
        "/api/tenants/acme-corp",
        headers=AUTH,
        json={"name": "Acme Corp", "terraform_dir": "~/infra/terraform", "cloud_provider": "az"},
    )
    assert r.status_code == 200
    assert r.json()["terraform_dir"] == "~/infra/terraform"
    assert r.json()["cloud_provider"] == "az"

    refetched = client.get("/api/tenants/acme-corp", headers=AUTH).json()
    assert refetched["terraform_dir"] == "~/infra/terraform"
    assert refetched["cloud_provider"] == "az"


def test_update_unknown_tenant_is_404(client):
    r = client.put("/api/tenants/does-not-exist", headers=AUTH, json={"name": "X"})
    assert r.status_code == 404


# ── delete ──────────────────────────────────────────────────────────────


def test_delete_then_list_no_longer_shows_it(client):
    r = client.delete("/api/tenants/acme-corp", headers=AUTH)
    assert r.status_code == 200

    listed = client.get("/api/tenants", headers=AUTH).json()
    assert "acme-corp" not in {t["id"] for t in listed["tenants"]}


def test_delete_default_tenant_is_400(client):
    r = client.delete("/api/tenants/demo", headers=AUTH)
    assert r.status_code == 400


def test_delete_unknown_tenant_is_404(client):
    r = client.delete("/api/tenants/does-not-exist", headers=AUTH)
    assert r.status_code == 404


# ── default ─────────────────────────────────────────────────────────────


def test_set_default_then_delete_previous_default_succeeds(client):
    r = client.put("/api/tenants/default", headers=AUTH, json={"tenant_id": "acme-corp"})
    assert r.status_code == 200

    r = client.delete("/api/tenants/demo", headers=AUTH)
    assert r.status_code == 200

    listed = client.get("/api/tenants", headers=AUTH).json()
    assert listed["default_tenant"] == "acme-corp"


def test_set_default_unknown_tenant_is_404(client):
    r = client.put("/api/tenants/default", headers=AUTH, json={"tenant_id": "nope"})
    assert r.status_code == 404
