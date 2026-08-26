"""
Unit tests for the parity tools (M4): kubectl_describe, kubectl_logs,
argocd_app_list/status, cloud_cli. A fake CommandExecutor records the
commands it receives and returns a canned result — no real subprocess here
(see test_exec.py for tests of LocalExecutor itself).
"""
import json

from app.agent.tools import argocd, cloud_cli, kubectl
from app.agent.tools.types import ToolContext
from app.config.schema import TenantConfig
from app.exec.base import CommandExecutor, ExecResult


class FakeExecutor(CommandExecutor):
    def __init__(self, result: ExecResult | None = None):
        self.result = result or ExecResult(stdout="", stderr="", returncode=0, command="")
        self.calls: list[dict] = []

    async def run(self, command, *, env=None, timeout=30, shell=False):
        self.calls.append({"command": command, "env": env, "timeout": timeout, "shell": shell})
        return self.result


def _ctx(executor: FakeExecutor) -> ToolContext:
    return ToolContext(tenant=TenantConfig(id="t1", name="T1"), executor=executor)


# ─── kubectl_describe ───────────────────────────────────────────────────

async def test_kubectl_describe_requires_resource_and_name():
    executor = FakeExecutor()
    result = await kubectl.KUBECTL_DESCRIBE_TOOL.execute({"resource": "pod"}, _ctx(executor))
    assert "error" in result
    assert executor.calls == []  # never executed, validation failed before


async def test_kubectl_describe_builds_expected_command():
    executor = FakeExecutor(ExecResult(stdout="Name: foo", stderr="", returncode=0, command=""))
    result = await kubectl.KUBECTL_DESCRIBE_TOOL.execute(
        {"resource": "pod", "name": "foo", "namespace": "demo"}, _ctx(executor)
    )
    assert executor.calls[0]["command"] == ["kubectl", "describe", "pod", "foo", "-n", "demo"]
    assert result["stdout"] == "Name: foo"


# ─── kubectl_logs ────────────────────────────────────────────────────────

async def test_kubectl_logs_requires_pod():
    executor = FakeExecutor()
    result = await kubectl.KUBECTL_LOGS_TOOL.execute({}, _ctx(executor))
    assert "error" in result


async def test_kubectl_logs_default_tail_and_optional_flags():
    executor = FakeExecutor()
    await kubectl.KUBECTL_LOGS_TOOL.execute({"pod": "foo"}, _ctx(executor))
    assert executor.calls[0]["command"] == ["kubectl", "logs", "foo", "--tail=50"]

    executor2 = FakeExecutor()
    await kubectl.KUBECTL_LOGS_TOOL.execute(
        {"pod": "foo", "namespace": "demo", "lines": 200, "container": "app"}, _ctx(executor2)
    )
    assert executor2.calls[0]["command"] == [
        "kubectl", "logs", "foo", "--tail=200", "-n", "demo", "-c", "app",
    ]


# ─── argocd ──────────────────────────────────────────────────────────────

async def test_argocd_app_list_default_namespace():
    executor = FakeExecutor()
    await argocd.ARGOCD_APP_LIST_TOOL.execute({}, _ctx(executor))
    cmd = executor.calls[0]["command"]
    assert cmd[:4] == ["kubectl", "get", "applications", "-n"]
    assert cmd[4] == "argocd"


async def test_argocd_app_status_requires_app_name():
    executor = FakeExecutor()
    result = await argocd.ARGOCD_APP_STATUS_TOOL.execute({}, _ctx(executor))
    assert "error" in result


async def test_argocd_app_status_parses_sync_and_health():
    payload = json.dumps({
        "status": {
            "sync": {"status": "Synced", "revision": "abcdef1234567890"},
            "health": {"status": "Healthy"},
            "conditions": [],
        }
    })
    executor = FakeExecutor(ExecResult(stdout=payload, stderr="", returncode=0, command=""))
    result = await argocd.ARGOCD_APP_STATUS_TOOL.execute({"app_name": "foo"}, _ctx(executor))
    assert result["sync_status"] == "Synced"
    assert result["health_status"] == "Healthy"
    assert result["revision"] == "abcdef12"  # truncated to 8 characters


async def test_argocd_app_status_handles_kubectl_error_gracefully():
    executor = FakeExecutor(ExecResult(stdout="", stderr="not found", returncode=1, command=""))
    result = await argocd.ARGOCD_APP_STATUS_TOOL.execute({"app_name": "does-not-exist"}, _ctx(executor))
    assert result["returncode"] == 1
    assert "not found" in result["stderr"]


# ─── cloud_cli ───────────────────────────────────────────────────────────

async def test_cloud_cli_requires_resource_type():
    executor = FakeExecutor()
    result = await cloud_cli.CLOUD_CLI_TOOL.execute({}, _ctx(executor))
    assert "error" in result
    assert executor.calls == []


async def test_cloud_cli_rejects_write_actions():
    executor = FakeExecutor()
    result = await cloud_cli.CLOUD_CLI_TOOL.execute(
        {"resource_type": "keyvault secret", "action": "delete"}, _ctx(executor)
    )
    assert "error" in result
    assert "not allowed" in result["error"]
    assert executor.calls == []  # never executed


async def test_cloud_cli_builds_expected_command_with_extra_args():
    executor = FakeExecutor()
    await cloud_cli.CLOUD_CLI_TOOL.execute(
        {
            "resource_type": "keyvault secret",
            "action": "list",
            "args": {"--vault-name": "mon-kv"},
        },
        _ctx(executor),
    )
    assert executor.calls[0]["command"] == [
        "az", "keyvault", "secret", "list", "--vault-name", "mon-kv", "-o", "table",
    ]


async def test_cloud_cli_parses_json_output():
    executor = FakeExecutor(ExecResult(stdout='[{"name": "foo"}]', stderr="", returncode=0, command=""))
    result = await cloud_cli.CLOUD_CLI_TOOL.execute(
        {"resource_type": "aks", "output_format": "json"}, _ctx(executor)
    )
    assert result["result"] == [{"name": "foo"}]
