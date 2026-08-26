import pytest
from fastapi.testclient import TestClient

from app.config.schema import TenantConfig
from app.config.tenants import resolve_tenant

FAKE_TENANT = TenantConfig(id="test-tenant", name="Test Tenant")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AEGIS_BACKEND_TOKENS", "test-token-1,test-token-2")
    from app.main import app

    # These tests are about auth, not tenant resolution (covered by
    # test_tenants_config.py) — isolated here with an override.
    app.dependency_overrides[resolve_tenant] = lambda: FAKE_TENANT
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_healthz_does_not_require_auth(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ping_requires_auth(client):
    r = client.get("/api/ping")
    assert r.status_code == 401


def test_ping_rejects_wrong_token(client):
    r = client.get("/api/ping", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_ping_accepts_valid_token(client):
    r = client.get("/api/ping", headers={"Authorization": "Bearer test-token-1"})
    assert r.status_code == 200
    assert r.json() == {"pong": True, "tenant": {"id": "test-tenant", "name": "Test Tenant"}}


def test_ping_accepts_second_valid_token_for_rotation(client):
    r = client.get("/api/ping", headers={"Authorization": "Bearer test-token-2"})
    assert r.status_code == 200


def test_no_tokens_configured_refuses_rather_than_open(monkeypatch):
    monkeypatch.delenv("AEGIS_BACKEND_TOKENS", raising=False)
    from app.main import app

    app.dependency_overrides[resolve_tenant] = lambda: FAKE_TENANT
    try:
        client = TestClient(app)
        r = client.get("/api/ping", headers={"Authorization": "Bearer anything"})
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()
