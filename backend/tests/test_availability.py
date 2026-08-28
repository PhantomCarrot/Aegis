"""
Unit tests for app/agent/tools/availability.py — a FakeExecutor (same
pattern as test_tools.py) simulates "binary found"/"binary missing"
without touching a real subprocess or PATH.
"""
from app.agent.tools import availability
from app.config.schema import TenantConfig
from app.exec.base import CommandExecutor, ExecResult


class FakeExecutor(CommandExecutor):
    def __init__(self, result: ExecResult):
        self.result = result
        self.calls: list[str] = []

    async def run(self, command, *, env=None, timeout=30, shell=False):
        self.calls.append(command)
        return self.result


async def test_binary_available_when_command_v_succeeds():
    executor = FakeExecutor(ExecResult(stdout="/usr/bin/kubectl", stderr="", returncode=0, command=""))
    available, reason = await availability.binary_available(executor, "kubectl")
    assert available is True
    assert reason is None
    assert executor.calls == ["command -v kubectl"]


async def test_binary_unavailable_when_command_v_fails():
    executor = FakeExecutor(ExecResult(stdout="", stderr="", returncode=1, command=""))
    available, reason = await availability.binary_available(executor, "kubectl")
    assert available is False
    assert reason is not None


async def test_binary_unavailable_on_executor_error():
    executor = FakeExecutor(ExecResult(stdout="", stderr="", returncode=-1, command="", error="SSH connect: timeout"))
    available, reason = await availability.binary_available(executor, "kubectl")
    assert available is False
    assert "timeout" in reason


async def test_probe_uses_shell_true():
    executor = FakeExecutor(ExecResult(stdout="", stderr="", returncode=0, command=""))
    await availability.binary_available(executor, "kubectl")
    # command -v is a shell builtin, not an executable — must not be exec()'d directly.
    assert executor.calls == ["command -v kubectl"]


async def test_result_is_cached_within_ttl():
    availability.reset_cache()
    executor = FakeExecutor(ExecResult(stdout="/usr/bin/az", stderr="", returncode=0, command=""))
    tenant = TenantConfig(id="t1", name="T1")

    r1 = await availability.tools_availability(tenant, executor, ["cloud_cli"])
    r2 = await availability.tools_availability(tenant, executor, ["cloud_cli"])

    assert r1 == {"cloud_cli": True}
    assert r2 == {"cloud_cli": True}
    assert len(executor.calls) == 1  # second call served from cache


async def test_cache_expires_after_ttl(monkeypatch):
    availability.reset_cache()
    executor = FakeExecutor(ExecResult(stdout="/usr/bin/az", stderr="", returncode=0, command=""))
    tenant = TenantConfig(id="t1", name="T1")

    clock = {"t": 1000.0}
    monkeypatch.setattr(availability.time, "monotonic", lambda: clock["t"])

    await availability.tools_availability(tenant, executor, ["cloud_cli"])
    clock["t"] += availability._CACHE_TTL + 1
    await availability.tools_availability(tenant, executor, ["cloud_cli"])

    assert len(executor.calls) == 2


async def test_run_command_is_always_available_without_a_probe():
    executor = FakeExecutor(ExecResult(stdout="", stderr="", returncode=1, command=""))
    tenant = TenantConfig(id="t1", name="T1")

    result = await availability.tools_availability(tenant, executor, ["run_command"])

    assert result == {"run_command": True}
    assert executor.calls == []


async def test_argocd_and_kubectl_share_the_kubectl_binary():
    """argocd_app_list/status run through `kubectl get applications`, not
    the `argocd` CLI (see agent/tools/argocd.py) — both groups must map to
    the same "kubectl" probe, and a missing kubectl must mark both unavailable."""
    availability.reset_cache()
    executor = FakeExecutor(ExecResult(stdout="", stderr="", returncode=1, command=""))
    tenant = TenantConfig(id="t1", name="T1")

    result = await availability.tools_availability(
        tenant, executor, ["kubectl_get", "argocd_app_list", "argocd_app_status"]
    )

    assert result == {"kubectl_get": False, "argocd_app_list": False, "argocd_app_status": False}
    assert executor.calls == ["command -v kubectl"]  # one probe, shared across both groups


async def test_cloud_cli_binary_follows_tenant_provider():
    availability.reset_cache()
    executor = FakeExecutor(ExecResult(stdout="/usr/bin/az", stderr="", returncode=0, command=""))
    tenant = TenantConfig(id="t1", name="T1", cloud_provider="az")

    result = await availability.tools_availability(tenant, executor, ["cloud_cli"])

    assert result == {"cloud_cli": True}
    assert executor.calls == ["command -v az"]
