"""
Registry of tools available to the agent. Each tool is a small module (one
file per tool, e.g. kubectl.py) exposing its definition; per-tenant
activation happens via `tenant.tools_enabled` (groups or precise names),
with an optional per-request runtime restriction (`override_names`) — see
docs/tools.md.
"""
from __future__ import annotations

from app.agent.tools import argocd, cloud_cli, kubectl, run_command
from app.agent.tools.types import Tool, ToolContext
from app.config.schema import TenantConfig

__all__ = ["Tool", "ToolContext", "get_enabled_tools", "get_tool", "tenant_allowed_tool_names", "tool_to_ollama_schema"]

_ALL_TOOLS: dict[str, Tool] = {
    "kubectl_get": kubectl.KUBECTL_GET_TOOL,
    "kubectl_describe": kubectl.KUBECTL_DESCRIBE_TOOL,
    "kubectl_logs": kubectl.KUBECTL_LOGS_TOOL,
    "argocd_app_list": argocd.ARGOCD_APP_LIST_TOOL,
    "argocd_app_status": argocd.ARGOCD_APP_STATUS_TOOL,
    "cloud_cli": cloud_cli.CLOUD_CLI_TOOL,
    "run_command": run_command.RUN_COMMAND_TOOL,
}

# tools_enabled can list a group ("kubectl") or a precise tool name
# ("kubectl_get") — both are resolved. Other groups (s3, kafka,
# observability...) will be added as more tools are ported (V1.1).
_TOOL_GROUPS: dict[str, set[str]] = {
    "kubectl": {"kubectl_get", "kubectl_describe", "kubectl_logs"},
    "argocd": {"argocd_app_list", "argocd_app_status"},
}


def tenant_allowed_tool_names(tenant: TenantConfig) -> set[str]:
    """The tools the tenant config allows — the upper bound, never exceedable at runtime."""
    allowed: set[str] = set()
    for entry in tenant.tools_enabled:
        allowed |= _TOOL_GROUPS.get(entry, {entry})
    return allowed & _ALL_TOOLS.keys()


def get_enabled_tools(tenant: TenantConfig, override_names: set[str] | None = None) -> list[Tool]:
    """
    Tools actually active for this request. `override_names` (from the UI,
    "toggle tools at runtime") can only NARROW the set allowed by the
    tenant config, never widen it — the tenant config remains the security
    boundary.
    """
    allowed = tenant_allowed_tool_names(tenant)
    if override_names is not None:
        allowed &= override_names
    return [tool for name, tool in _ALL_TOOLS.items() if name in allowed]


def get_tool(name: str) -> Tool | None:
    return _ALL_TOOLS.get(name)


def tool_to_ollama_schema(tool: Tool) -> dict:
    """
    Exact representation sent to Ollama for this tool — what the LLM sees
    to decide whether to call it. Exposed as-is via GET /api/tools so the
    operator can inspect it (see docs/tools.md).
    """
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
