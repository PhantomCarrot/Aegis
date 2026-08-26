"""
cloud_cli — queries cloud resources, read-only only.

V1 supports Azure (the `az` CLI) — it's the only wired provider, but
nothing about this tool's shape is specific to it (generic
resource_type/action/args); adding AWS/GCP would follow the same pattern
without changing the interface exposed to the LLM. Always "safe": the tool
itself refuses any action that isn't list/show/get/describe, no guardrail
needed.
"""
from __future__ import annotations

import json
import shlex

from app.agent.tools.types import Tool, ToolContext

_ALLOWED_ACTIONS = {"list", "show", "get", "describe"}


async def _run_cloud_cli(args: dict, ctx: ToolContext) -> dict:
    resource_type = (args.get("resource_type") or "").strip()
    if not resource_type:
        return {"error": "cloud_cli requires 'resource_type'"}

    action = (args.get("action") or "list").strip()
    if action not in _ALLOWED_ACTIONS:
        return {"error": f"Action '{action}' not allowed — read-only (list/show/get/describe)"}

    extra: dict = args.get("args") or {}
    fmt = args.get("output_format", "table")

    cmd = ["az"] + shlex.split(resource_type) + [action]
    for k, v in extra.items():
        cmd += [str(k), str(v)]
    cmd += ["-o", fmt]

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
    description=(
        "Queries cloud resources — Azure (az CLI) in V1. Read-only: "
        "list/show/get/describe only. Examples: resource_type='keyvault secret', "
        "action='list', args={'--vault-name': 'my-kv'} ; resource_type='aks', action='list' ; "
        "resource_type='storage account', action='list'."
    ),
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
