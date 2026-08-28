"""
cloud_cli — queries cloud resources, read-only only.

The LLM-facing tool name/interface stays stable regardless of provider —
which cloud CLI grammar actually answers a call is resolved per tenant via
app/agent/tools/cloud_providers.py (tenant.cloud_provider), same dispatch
pattern as app/stream/providers.py for LLM providers. Only Azure (az CLI)
is wired today — see docs/tools.md. Always "safe": the tool itself refuses
any action the provider doesn't allow (list/show/get/describe for Azure),
no guardrail needed.
"""
from __future__ import annotations

import json

from app.agent.tools import azure_cli
from app.agent.tools.cloud_providers import get_cloud_provider
from app.agent.tools.types import Tool, ToolContext


async def _run_cloud_cli(args: dict, ctx: ToolContext) -> dict:
    resource_type = (args.get("resource_type") or "").strip()
    if not resource_type:
        return {"error": "cloud_cli requires 'resource_type'"}

    action = (args.get("action") or "list").strip()
    provider = get_cloud_provider(ctx.tenant)
    error = provider.validate_action(action)
    if error:
        return {"error": error}

    extra: dict = args.get("args") or {}
    fmt = args.get("output_format", "table")

    cmd = provider.build_command(resource_type, action, extra, fmt)

    result = await ctx.executor.run(cmd, timeout=60)
    output: dict = {
        "command": " ".join(cmd),
        "returncode": result.returncode,
        "stdout": result.stdout[:8000],
        "stderr": result.stderr[:1000] if result.returncode != 0 else "",
    }
    if result.error:
        output["error"] = result.error
    elif fmt == "json" and result.returncode == 0:
        try:
            output["result"] = json.loads(result.stdout)
        except json.JSONDecodeError:
            pass
    return output


CLOUD_CLI_TOOL = Tool(
    name="cloud_cli",
    # Static for V1 (azure_cli.TOOL_DESCRIPTION, not built per-tenant): the
    # only implemented provider today is Azure, so this stays accurate for
    # every tenant that can actually pass config validation. Making it
    # dynamic per-tenant would need threading `tenant` into
    # tool_to_ollama_schema() at both its call sites — not worth doing
    # ahead of a second provider that doesn't exist yet.
    description=azure_cli.TOOL_DESCRIPTION,
    parameters={
        "type": "object",
        "properties": {
            "resource_type": {
                "type": "string",
                "description": "e.g. 'keyvault secret', 'aks', 'storage account', 'group'",
            },
            "action": {"type": "string", "description": "'list' (default), 'show', 'get' or 'describe'"},
            "args": {"type": "object", "description": "extra arguments, e.g. {'--vault-name': 'x'}"},
            "output_format": {"type": "string", "description": "'table' (default) or 'json'"},
        },
        "required": ["resource_type"],
    },
    execute=_run_cloud_cli,
)
