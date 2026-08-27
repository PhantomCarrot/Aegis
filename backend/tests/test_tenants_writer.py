"""
app/config/writer.py — the persistence side of tenant administration
(create/edit/delete a tenant from the UI). See test_tenants_config.py for
the read/hot-reload side.
"""
import threading

import pytest

from app.config import writer

EXISTING_TENANTS_YAML = """default_tenant: demo
tenants:
  demo:
    name: "Demo"
    tools_enabled: [kubectl, run_command]
  # Acme bastion access — Azure AD cert auth, refreshed via `az ssh
  # config` roughly every hour; see docs/execution-model.md for the full
  # certificate-auth walkthrough across cloud providers.
  acme-corp:
    name: "Acme Corp"
    exec:
      mode: ssh
      ssh:
        host: "10.0.0.5"
        user: "opsagent"
        key_path: "~/.ssh/aegis_acme"
    tools_enabled: [kubectl, argocd]
"""


@pytest.fixture
def tenants_file(tmp_path):
    f = tmp_path / "tenants.yaml"
    f.write_text(EXISTING_TENANTS_YAML)
    return f


@pytest.fixture
def global_file(tmp_path):
    # Absent on purpose — writer.py must fall back to Python defaults, same
    # as TenantRegistry does.
    return tmp_path / "absent-global.yaml"


# ── create ──────────────────────────────────────────────────────────────


def test_create_bootstraps_a_missing_file(tmp_path, global_file):
    fresh = tmp_path / "fresh-tenants.yaml"
    resolved = writer.create_tenant(
        "first", {"name": "First"}, tenants_path=fresh, global_path=global_file
    )
    assert resolved.id == "first"
    assert fresh.exists()

    raw = fresh.read_text()
    assert "first" in raw
    # First tenant created on a fresh file becomes the default automatically
    # — otherwise the file would be invalid on the very next read.
    assert "default_tenant: first" in raw


def test_create_adds_a_tenant_to_an_existing_file(tenants_file, global_file):
    resolved = writer.create_tenant(
        "verify-test",
        {"name": "Verify Test", "tools_enabled": ["run_command"]},
        tenants_path=tenants_file,
        global_path=global_file,
    )
    assert resolved.id == "verify-test"
    assert resolved.name == "Verify Test"
    assert resolved.kubeconfig_dir == "~/.kube/aegis/verify-test"

    raw = tenants_file.read_text()
    assert "verify-test" in raw
    # Existing tenants and the default are untouched.
    assert "default_tenant: demo" in raw
    assert "demo" in raw and "acme-corp" in raw


def test_create_duplicate_id_raises_without_writing(tenants_file, global_file):
    before = tenants_file.read_text()
    with pytest.raises(writer.TenantAlreadyExistsError):
        writer.create_tenant(
            "demo", {"name": "Dup"}, tenants_path=tenants_file, global_path=global_file
        )
    assert tenants_file.read_text() == before


def test_create_invalid_config_raises_and_writes_nothing(tenants_file, global_file):
    before = tenants_file.read_text()
    with pytest.raises(writer.TenantValidationError):
        writer.create_tenant(
            "bad",
            {"name": "Bad", "exec": {"mode": "ssh"}},  # ssh mode without an ssh block
            tenants_path=tenants_file,
            global_path=global_file,
        )
    assert tenants_file.read_text() == before


# ── update ──────────────────────────────────────────────────────────────


def test_update_changes_the_target_tenant_only(tenants_file, global_file):
    resolved = writer.update_tenant(
        "demo",
        {"name": "Demo (renamed)", "domain_notes": "line one\nline two"},
        tenants_path=tenants_file,
        global_path=global_file,
    )
    assert resolved.name == "Demo (renamed)"
    assert resolved.domain_notes == "line one\nline two"

    raw = tenants_file.read_text()
    assert "Demo (renamed)" in raw
    # acme-corp and its comment are untouched by an update to a *different* tenant.
    assert "Acme Corp" in raw
    assert "Acme bastion access" in raw


def test_update_unknown_tenant_raises(tenants_file, global_file):
    with pytest.raises(writer.TenantMissingError):
        writer.update_tenant(
            "does-not-exist", {"name": "X"}, tenants_path=tenants_file, global_path=global_file
        )


def test_update_multiline_domain_notes_round_trips(tenants_file, global_file):
    notes = "First line.\nSecond line with detail.\n\nA blank-line-separated paragraph."
    writer.update_tenant(
        "demo", {"name": "Demo", "domain_notes": notes}, tenants_path=tenants_file, global_path=global_file
    )
    resolved = writer.update_tenant(
        "demo", {"name": "Demo", "domain_notes": notes}, tenants_path=tenants_file, global_path=global_file
    )
    assert resolved.domain_notes == notes


# ── delete ──────────────────────────────────────────────────────────────


def test_delete_removes_a_non_default_tenant(tenants_file):
    writer.delete_tenant("acme-corp", tenants_path=tenants_file)
    raw = tenants_file.read_text()
    assert "acme-corp" not in raw
    # demo (the default) and its own comment-free block are untouched.
    assert "demo" in raw


def test_delete_unknown_tenant_raises(tenants_file):
    with pytest.raises(writer.TenantMissingError):
        writer.delete_tenant("does-not-exist", tenants_path=tenants_file)


def test_delete_current_default_tenant_refused(tenants_file):
    before = tenants_file.read_text()
    with pytest.raises(writer.CannotDeleteDefaultTenantError):
        writer.delete_tenant("demo", tenants_path=tenants_file)
    assert tenants_file.read_text() == before


def test_delete_sole_tenant_refused_as_the_default(tmp_path):
    # The common case: a single tenant is necessarily the default (a file
    # with no default_tenant is itself invalid), so this hits
    # CannotDeleteDefaultTenantError before the last-tenant guard even runs.
    only = tmp_path / "tenants.yaml"
    only.write_text("default_tenant: solo\ntenants:\n  solo:\n    name: Solo\n")
    with pytest.raises(writer.CannotDeleteDefaultTenantError):
        writer.delete_tenant("solo", tenants_path=only)


def test_delete_last_remaining_tenant_refused_even_if_not_marked_default(tmp_path):
    # Edge case the default-tenant guard alone wouldn't catch: a
    # hand-corrupted file where the one remaining tenant isn't (or is no
    # longer) default_tenant. Still refused — deleting it would leave the
    # file with an empty tenants: map, which TenantsFile can't resolve.
    only = tmp_path / "tenants.yaml"
    only.write_text("default_tenant: someone-else\ntenants:\n  solo:\n    name: Solo\n")
    with pytest.raises(writer.CannotDeleteLastTenantError):
        writer.delete_tenant("solo", tenants_path=only)


# ── set_default_tenant ──────────────────────────────────────────────────


def test_set_default_tenant_changes_default(tenants_file):
    writer.set_default_tenant("acme-corp", tenants_path=tenants_file)
    assert "default_tenant: acme-corp" in tenants_file.read_text()


def test_set_default_tenant_unknown_id_raises(tenants_file):
    with pytest.raises(writer.TenantMissingError):
        writer.set_default_tenant("does-not-exist", tenants_path=tenants_file)


def test_set_default_then_delete_previous_default_succeeds(tenants_file):
    writer.set_default_tenant("acme-corp", tenants_path=tenants_file)
    writer.delete_tenant("demo", tenants_path=tenants_file)
    raw = tenants_file.read_text()
    assert "demo" not in raw
    assert "default_tenant: acme-corp" in raw


# ── concurrency ─────────────────────────────────────────────────────────


def test_concurrent_creates_dont_corrupt_the_file(tenants_file, global_file):
    errors = []

    def make(i):
        try:
            writer.create_tenant(
                f"concurrent-{i}", {"name": f"C{i}"}, tenants_path=tenants_file, global_path=global_file
            )
        except Exception as e:  # noqa: BLE001 — recorded, not swallowed
            errors.append(e)

    threads = [threading.Thread(target=make, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    raw = tenants_file.read_text()
    for i in range(8):
        assert f"concurrent-{i}" in raw
    # Original tenants and comments survived eight concurrent writers.
    assert "Acme bastion access" in raw
