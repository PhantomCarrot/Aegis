from app.agent.tools.types import ToolContext
from app.config.schema import TenantConfig
from app.exec.base import CommandExecutor, ExecResult
from app.rag import terraform_gen

TERRAFORM_STATE_WITH_NESTED_MODULE = """
{
  "values": {
    "root_module": {
      "resources": [
        {
          "address": "azurerm_resource_group.main",
          "mode": "managed",
          "type": "azurerm_resource_group",
          "provider_name": "registry.terraform.io/hashicorp/azurerm",
          "values": {"name": "demo-rg", "location": "westeurope"}
        }
      ],
      "child_modules": [
        {
          "resources": [
            {
              "address": "module.aks.azurerm_kubernetes_cluster.main",
              "mode": "managed",
              "type": "azurerm_kubernetes_cluster",
              "provider_name": "registry.terraform.io/hashicorp/azurerm",
              "values": {"name": "demo-aks", "node_count": 3}
            }
          ]
        }
      ]
    }
  }
}
"""


class FakeExecutor(CommandExecutor):
    def __init__(self, result: ExecResult):
        self.result = result
        self.calls: list = []

    async def run(self, command, *, env=None, timeout=30, shell=False):
        self.calls.append((command, shell))
        return self.result


def _tenant(**overrides) -> TenantConfig:
    return TenantConfig(id="demo", name="Demo", **overrides)


async def test_returns_none_and_never_calls_executor_when_terraform_dir_unset():
    executor = FakeExecutor(ExecResult(stdout="", stderr="", returncode=0, command=""))
    ctx = ToolContext(tenant=_tenant(), executor=executor)

    markdown = await terraform_gen.generate_terraform_overview(ctx)

    assert markdown is None
    assert executor.calls == []


async def test_runs_a_shell_string_with_cd_and_terraform_show():
    executor = FakeExecutor(ExecResult(stdout=TERRAFORM_STATE_WITH_NESTED_MODULE, stderr="", returncode=0, command=""))
    ctx = ToolContext(tenant=_tenant(terraform_dir="/infra/terraform"), executor=executor)

    await terraform_gen.generate_terraform_overview(ctx)

    assert len(executor.calls) == 1
    command, shell = executor.calls[0]
    assert isinstance(command, str)  # not a list, unlike every other tool
    assert command.startswith("cd ")
    assert "terraform show -json" in command
    assert shell is True


async def test_includes_resources_from_nested_child_modules():
    executor = FakeExecutor(ExecResult(stdout=TERRAFORM_STATE_WITH_NESTED_MODULE, stderr="", returncode=0, command=""))
    ctx = ToolContext(tenant=_tenant(terraform_dir="/infra/terraform"), executor=executor)

    markdown = await terraform_gen.generate_terraform_overview(ctx)

    assert "# Terraform State — Demo" in markdown
    assert "## azurerm_resource_group.main" in markdown
    assert "demo-rg" in markdown
    # the nested resource, from child_modules — proves recursion
    assert "## module.aks.azurerm_kubernetes_cluster.main" in markdown
    assert "demo-aks" in markdown


async def test_command_failure_lands_visibly_in_the_doc_without_raising():
    executor = FakeExecutor(ExecResult(stdout="", stderr="terraform: command not found", returncode=127, command=""))
    ctx = ToolContext(tenant=_tenant(terraform_dir="/infra/terraform"), executor=executor)

    markdown = await terraform_gen.generate_terraform_overview(ctx)

    assert "terraform: command not found" in markdown


async def test_malformed_json_lands_visibly_without_raising():
    executor = FakeExecutor(ExecResult(stdout="not json at all", stderr="", returncode=0, command=""))
    ctx = ToolContext(tenant=_tenant(terraform_dir="/infra/terraform"), executor=executor)

    markdown = await terraform_gen.generate_terraform_overview(ctx)

    assert "not json at all" in markdown


async def test_empty_state_renders_no_resources_found():
    executor = FakeExecutor(ExecResult(stdout='{"values": {}}', stderr="", returncode=0, command=""))
    ctx = ToolContext(tenant=_tenant(terraform_dir="/infra/terraform"), executor=executor)

    markdown = await terraform_gen.generate_terraform_overview(ctx)

    assert "no resources found" in markdown
