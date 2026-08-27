"""GET /api/tools — tool introspection: which are enabled for this tenant,
and with what exact schema they're presented to the LLM (see docs/tools.md)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agent.tools.registry import _ALL_TOOLS, tenant_allowed_tool_names, tool_to_ollama_schema, ui_tool_groups
from app.config.schema import TenantConfig
from app.config.tenants import resolve_tenant
from app.security.auth import RequireAuth

router = APIRouter(prefix="/api", tags=["tools"], dependencies=[RequireAuth])


@router.get("/tools")
def list_tools(tenant: Annotated[TenantConfig, Depends(resolve_tenant)]) -> dict:
    """
    Every tool known to the backend, with for each:
    - `enabled`: allowed by `tenant.tools_enabled` (the upper bound — what
      the UI's runtime toggle can restrict but never exceed)
    - `guarded`: subject to guardrails (classify is not None), e.g. run_command
    - `schema`: the exact JSON representation sent to Ollama for this tool
      (function-calling), so the operator can inspect it as-is.
    """
    allowed = tenant_allowed_tool_names(tenant)
    return {
        "tools": [
            {
                "name": name,
                "enabled": name in allowed,
                "guarded": tool.classify is not None,
                "schema": tool_to_ollama_schema(tool),
            }
            for name, tool in sorted(_ALL_TOOLS.items())
        ],
        # Group-level identifiers (kubectl, argocd, cloud_cli, run_command)
        # for a "which tools" checklist — see the tenant-admin UI, which
        # writes these directly into tenant.tools_enabled.
        "groups": ui_tool_groups(),
    }
