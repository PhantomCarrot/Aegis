from app.config.schema import TenantConfig
from app.exec.factory import describe_executor


def test_local_target():
    tenant = TenantConfig(id="demo", name="Demo")
    assert describe_executor(tenant) == "local"


def test_ssh_target_includes_user_host_port():
    tenant = TenantConfig(
        id="acme",
        name="Acme",
        exec={"mode": "ssh", "ssh": {"host": "10.0.0.5", "user": "opsagent", "port": 2222, "key_path": "~/.ssh/id"}},
    )
    assert describe_executor(tenant) == "ssh://opsagent@10.0.0.5:2222"
