from app.agent.tools.types import ToolContext
from app.config.schema import TenantConfig
from app.exec.base import CommandExecutor, ExecResult
from app.rag import docs_gen


class FakeExecutor(CommandExecutor):
    def __init__(self):
        self.calls: list[list[str]] = []

    async def run(self, command, *, env=None, timeout=30, shell=False):
        self.calls.append(command)
        # Returns output that identifies the requested resource, to verify
        # that each section of the doc contains the right command.
        resource = command[2]  # kubectl get <resource> ...
        return ExecResult(stdout=f"fake-{resource}-output", stderr="", returncode=0, command=" ".join(command))


async def test_generate_overview_scrapes_four_sections():
    executor = FakeExecutor()
    ctx = ToolContext(tenant=TenantConfig(id="demo", name="Demo"), executor=executor)

    markdown = await docs_gen.generate_overview(ctx)

    assert len(executor.calls) == 4
    resources_queried = {call[2] for call in executor.calls}
    assert resources_queried == {"ns", "pods", "deployments", "services"}

    assert "# Cluster Overview — Demo" in markdown
    assert "## Namespaces" in markdown
    assert "fake-ns-output" in markdown
    assert "fake-pods-output" in markdown


async def test_generate_overview_handles_command_failure_gracefully():
    class FailingExecutor(CommandExecutor):
        async def run(self, command, *, env=None, timeout=30, shell=False):
            return ExecResult(stdout="", stderr="connection refused", returncode=1, command=" ".join(command))

    ctx = ToolContext(tenant=TenantConfig(id="demo", name="Demo"), executor=FailingExecutor())
    markdown = await docs_gen.generate_overview(ctx)

    assert "connection refused" in markdown  # visible in the doc rather than an exception
