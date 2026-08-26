import time

import pytest

from app.config.tenants import TenantNotFoundError, TenantRegistry, TenantsConfigError

VALID_TENANTS_YAML = """
default_tenant: demo
tenants:
  demo:
    name: "Demo"
    tools_enabled: [kubectl, run_command]
  acme-corp:
    name: "Acme Corp"
    ollama:
      url: "http://ollama.acme.internal:11434"
    exec:
      mode: ssh
      ssh:
        host: "10.0.0.5"
        user: "opsagent"
        key_path: "~/.ssh/aegis_acme"
    tools_enabled: [kubectl, argocd]
"""

@pytest.fixture
def config_dir(tmp_path):
    tenants_file = tmp_path / "tenants.yaml"
    tenants_file.write_text(VALID_TENANTS_YAML)
    return tmp_path


def test_loads_tenants_and_applies_global_defaults(tmp_path, config_dir):
    # config/global.yaml IS directly the content of the defaults (see schema.py) —
    # no nested "defaults:" key.
    global_file = tmp_path / "global.yaml"
    global_file.write_text("exec:\n  mode: local\n")

    registry = TenantRegistry(global_path=global_file, tenants_path=config_dir / "tenants.yaml")

    demo = registry.get("demo")
    assert demo.name == "Demo"
    assert demo.exec.mode == "local"  # inherited from global
    assert demo.tools_enabled == ["kubectl", "run_command"]

    acme = registry.get("acme-corp")
    assert acme.exec.mode == "ssh"
    assert acme.exec.ssh is not None
    assert acme.exec.ssh.host == "10.0.0.5"
    assert acme.ollama.url == "http://ollama.acme.internal:11434"


def test_missing_global_config_falls_back_to_python_defaults(config_dir, tmp_path):
    missing_global = tmp_path / "does-not-exist.yaml"
    registry = TenantRegistry(global_path=missing_global, tenants_path=config_dir / "tenants.yaml")

    demo = registry.get("demo")
    assert demo.exec.mode == "local"
    assert demo.ollama.url == "http://localhost:11434"


def test_default_tenant_id_resolves(config_dir, tmp_path):
    registry = TenantRegistry(global_path=tmp_path / "absent.yaml", tenants_path=config_dir / "tenants.yaml")
    assert registry.default_tenant_id == "demo"


def test_unknown_tenant_raises(config_dir, tmp_path):
    registry = TenantRegistry(global_path=tmp_path / "absent.yaml", tenants_path=config_dir / "tenants.yaml")
    with pytest.raises(TenantNotFoundError):
        registry.get("does-not-exist")


def test_missing_tenants_file_raises_clear_error(tmp_path):
    registry = TenantRegistry(
        global_path=tmp_path / "absent-global.yaml",
        tenants_path=tmp_path / "absent-tenants.yaml",
    )
    with pytest.raises(TenantsConfigError, match="tenants.yaml.example"):
        registry.get("anything")


def test_invalid_default_tenant_raises(tmp_path):
    bad = tmp_path / "tenants.yaml"
    bad.write_text("default_tenant: nope\ntenants:\n  demo:\n    name: Demo\n")
    registry = TenantRegistry(global_path=tmp_path / "absent.yaml", tenants_path=bad)
    with pytest.raises(TenantsConfigError, match="default_tenant"):
        registry.list_tenants()


def test_ssh_mode_without_ssh_block_raises(tmp_path):
    bad = tmp_path / "tenants.yaml"
    bad.write_text(
        "default_tenant: demo\n"
        "tenants:\n"
        "  demo:\n"
        "    name: Demo\n"
        "    exec:\n"
        "      mode: ssh\n"
    )
    registry = TenantRegistry(global_path=tmp_path / "absent.yaml", tenants_path=bad)
    with pytest.raises(TenantsConfigError, match="ssh"):
        registry.get("demo")


def test_kubeconfig_dir_defaults_are_tenant_scoped_not_shared(config_dir, tmp_path):
    """
    Two tenants that don't specify kubeconfig_dir must NEVER share the same
    default — otherwise one's kubeconfig could leak to the other. See the
    note in schema.py.
    """
    registry = TenantRegistry(global_path=tmp_path / "absent.yaml", tenants_path=config_dir / "tenants.yaml")
    demo = registry.get("demo")
    acme = registry.get("acme-corp")
    assert demo.kubeconfig_dir != acme.kubeconfig_dir
    assert demo.id in demo.kubeconfig_dir
    assert acme.id in acme.kubeconfig_dir


def test_hot_reload_picks_up_changes_without_restart(config_dir, tmp_path):
    tenants_path = config_dir / "tenants.yaml"
    registry = TenantRegistry(global_path=tmp_path / "absent.yaml", tenants_path=tenants_path)

    assert registry.get("demo").name == "Demo"

    # mtime has second-level resolution on some filesystems — force the gap.
    time.sleep(1.1)
    tenants_path.write_text(
        "default_tenant: demo\n"
        "tenants:\n"
        "  demo:\n"
        "    name: 'Demo (renamed)'\n"
    )

    assert registry.get("demo").name == "Demo (renamed)"
