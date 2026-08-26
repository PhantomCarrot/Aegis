"""
Tests for the tool registry (app/agent/tools/registry.py): resolving the
groups/names a tenant allows, and above all the security boundary of
`override_names` — the runtime (UI) toggle must never be able to enable a
tool the tenant config doesn't allow, only disable one.
"""
from app.agent.tools.registry import (
    get_enabled_tools,
    get_tool,
    tenant_allowed_tool_names,
    tool_to_ollama_schema,
)
from app.config.schema import TenantConfig


def _tenant(tools_enabled: list[str]) -> TenantConfig:
    return TenantConfig(id="t1", name="T1", tools_enabled=tools_enabled)


def test_tenant_allowed_tool_names_resolves_groups():
    tenant = _tenant(["kubectl", "run_command"])
    allowed = tenant_allowed_tool_names(tenant)
    assert allowed == {"kubectl_get", "kubectl_describe", "kubectl_logs", "run_command"}


def test_tenant_allowed_tool_names_resolves_precise_names():
    tenant = _tenant(["kubectl_get", "cloud_cli"])
    assert tenant_allowed_tool_names(tenant) == {"kubectl_get", "cloud_cli"}


def test_get_enabled_tools_without_override_matches_tenant_config():
    tenant = _tenant(["kubectl", "argocd"])
    names = {t.name for t in get_enabled_tools(tenant)}
    assert names == {"kubectl_get", "kubectl_describe", "kubectl_logs", "argocd_app_list", "argocd_app_status"}


def test_override_names_can_only_narrow_never_expand():
    """
    Security boundary: override_names comes from the UI (runtime toggle).
    Even if the UI sends a tool the tenant doesn't allow, it must never
    show up in the result.
    """
    tenant = _tenant(["kubectl_get"])  # config = upper bound: only one tool allowed

    # The UI tries to widen the set by also requesting cloud_cli, not allowed by the tenant.
    names = {t.name for t in get_enabled_tools(tenant, override_names={"kubectl_get", "cloud_cli"})}
    assert names == {"kubectl_get"}  # cloud_cli stays excluded despite the request


def test_override_names_narrows_normally():
    tenant = _tenant(["kubectl"])  # 3 kubectl tools allowed
    names = {t.name for t in get_enabled_tools(tenant, override_names={"kubectl_get"})}
    assert names == {"kubectl_get"}


def test_override_names_empty_set_disables_everything():
    tenant = _tenant(["kubectl", "run_command"])
    assert get_enabled_tools(tenant, override_names=set()) == []


def test_get_tool_unknown_name_returns_none():
    assert get_tool("does-not-exist") is None


def test_tool_to_ollama_schema_matches_function_calling_shape():
    tool = get_tool("kubectl_get")
    schema = tool_to_ollama_schema(tool)
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "kubectl_get"
    assert schema["function"]["description"] == tool.description
    assert schema["function"]["parameters"] == tool.parameters
