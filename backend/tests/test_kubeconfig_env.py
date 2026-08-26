"""
Tests for kubeconfig_env() — the KUBECONFIG value it builds only makes
sense for local execution (a path on the backend's own filesystem). See
docs/execution-model.md for why SSH-mode tenants get no override at all.
"""
from app.agent.tools.env import kubeconfig_env
from app.agent.tools.types import ToolContext
from app.config.schema import TenantConfig
from app.exec.local import LocalExecutor


def _ctx(tenant: TenantConfig) -> ToolContext:
    return ToolContext(tenant=tenant, executor=LocalExecutor())


def test_local_mode_sets_explicit_kubeconfig(tmp_path):
    kube_dir = tmp_path / "kube"
    kube_dir.mkdir()
    (kube_dir / "a.yaml").write_text("x")
    (kube_dir / "b.yaml").write_text("x")

    tenant = TenantConfig(id="t1", name="T1", kubeconfig_dir=str(kube_dir))
    env = kubeconfig_env(_ctx(tenant))

    assert env is not None
    assert env["KUBECONFIG"] == f"{kube_dir / 'a.yaml'}:{kube_dir / 'b.yaml'}"


def test_local_mode_with_no_kubeconfig_files_points_to_nonexistent_path(tmp_path):
    kube_dir = tmp_path / "empty-kube"
    tenant = TenantConfig(id="t2", name="T2", kubeconfig_dir=str(kube_dir))
    env = kubeconfig_env(_ctx(tenant))

    assert env is not None
    assert env["KUBECONFIG"] == str(kube_dir / "none.yaml")


def test_ssh_mode_returns_no_override():
    tenant = TenantConfig(
        id="t3", name="T3",
        exec={"mode": "ssh", "ssh": {"host": "10.0.0.1", "user": "ops", "key_path": "~/.ssh/id_aegis"}},
    )
    assert kubeconfig_env(_ctx(tenant)) is None
