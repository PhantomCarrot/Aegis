import os

import pytest

from app.config.schema import TenantConfig
from app.exec.factory import get_executor
from app.exec.local import LocalExecutor
from app.exec.ssh import SSHExecutor


async def test_local_executor_runs_argv_list():
    executor = LocalExecutor()
    result = await executor.run(["echo", "hello aegis"])
    assert result.ok
    assert result.stdout.strip() == "hello aegis"
    assert result.returncode == 0


async def test_local_executor_runs_shell_pipeline():
    executor = LocalExecutor()
    result = await executor.run("echo hello | tr a-z A-Z", shell=True)
    assert result.ok
    assert result.stdout.strip() == "HELLO"


async def test_local_executor_reports_missing_binary():
    executor = LocalExecutor()
    result = await executor.run(["this-binary-does-not-exist-aegis"])
    assert not result.ok
    assert result.error is not None


async def test_local_executor_times_out():
    executor = LocalExecutor()
    result = await executor.run(["sleep", "5"], timeout=1)
    assert not result.ok
    assert "Timeout" in (result.error or "")


def test_factory_returns_local_executor_by_default():
    tenant = TenantConfig(id="t1", name="T1")
    assert isinstance(get_executor(tenant), LocalExecutor)


def test_factory_returns_ssh_executor_and_reuses_it():
    tenant = TenantConfig(
        id="t2",
        name="T2",
        exec={
            "mode": "ssh",
            "ssh": {"host": "10.0.0.1", "user": "ops", "key_path": "~/.ssh/id_aegis"},
        },
    )
    first = get_executor(tenant)
    second = get_executor(tenant)
    assert isinstance(first, SSHExecutor)
    assert first is second  # connection reused, not recreated per request


def test_ssh_mode_without_config_rejected_at_schema_level():
    with pytest.raises(Exception):
        TenantConfig(id="t3", name="T3", exec={"mode": "ssh"})


async def test_ssh_executor_passes_client_certs_when_configured(monkeypatch):
    """
    Certificate-based auth (e.g. Azure AD `az ssh config`, Vault SSH
    secrets engine) pairs a short-lived certificate with the private key —
    asyncssh.connect() must receive it as client_certs, not just client_keys.
    """
    from app.config.schema import SSHExecConfig

    captured: dict = {}

    async def fake_connect(host, **kwargs):
        captured["host"] = host
        captured.update(kwargs)
        return object()  # stand-in connection, .is_closed() not called here

    import app.exec.ssh as ssh_module
    monkeypatch.setattr(ssh_module.asyncssh, "connect", fake_connect)

    config = SSHExecConfig(
        host="10.0.0.1", user="ops", key_path="~/.ssh/id_aegis",
        certificate_path="~/.ssh/id_aegis-cert.pub",
    )
    executor = SSHExecutor(config)
    await executor._connection()

    assert captured["client_certs"] == [os.path.expanduser("~/.ssh/id_aegis-cert.pub")]


async def test_ssh_executor_omits_client_certs_when_not_configured(monkeypatch):
    from app.config.schema import SSHExecConfig

    captured: dict = {}

    async def fake_connect(host, **kwargs):
        captured.update(kwargs)
        return object()

    import app.exec.ssh as ssh_module
    monkeypatch.setattr(ssh_module.asyncssh, "connect", fake_connect)

    config = SSHExecConfig(host="10.0.0.1", user="ops", key_path="~/.ssh/id_aegis")
    executor = SSHExecutor(config)
    await executor._connection()

    assert "client_certs" not in captured
