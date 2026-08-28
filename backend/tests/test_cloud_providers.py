"""
Unit tests for the cloud_cli provider dispatcher (see
app/agent/tools/cloud_providers.py) — mirrors the shape of tests for
app/stream/providers.py's LLM-provider dispatch, but that file has no test
of its own to mirror exactly, so this is the first of its kind.
"""
from app.agent.tools import azure_cli
from app.agent.tools.cloud_providers import get_cloud_provider
from app.config.schema import TenantConfig


def test_default_provider_is_azure():
    provider = get_cloud_provider(TenantConfig(id="t1", name="T1"))
    assert provider.binary == "az"
    assert provider.validate_action is azure_cli.validate_action
    assert provider.build_command is azure_cli.build_command


def test_azure_provider_builds_expected_command():
    provider = get_cloud_provider(TenantConfig(id="t1", name="T1"))
    cmd = provider.build_command("keyvault secret", "list", {"--vault-name": "my-kv"}, "table")
    assert cmd == ["az", "keyvault", "secret", "list", "--vault-name", "my-kv", "-o", "table"]


def test_azure_provider_rejects_write_actions():
    provider = get_cloud_provider(TenantConfig(id="t1", name="T1"))
    assert provider.validate_action("delete") is not None
    assert provider.validate_action("list") is None
