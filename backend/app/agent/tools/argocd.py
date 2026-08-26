"""
argocd_app_list / argocd_app_status — read-only, always "safe".

Goes through `kubectl get applications` (the ArgoCD CRD) rather than the
dedicated `argocd` CLI: avoids an extra authentication dependency, the
tenant's kubeconfig is already enough to read Applications.
"""
from __future__ import annotations

import json

from app.agent.tools.env import kubeconfig_env
from app.agent.tools.types import Tool, ToolContext


async def _run_argocd_app_list(args: dict, ctx: ToolContext) -> dict:
    namespace = args.get("namespace", "argocd")
    cmd = [
        "kubectl", "get", "applications", "-n", namespace, "-o",
        "custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status",
    ]
    result = await ctx.executor.run(cmd, env=kubeconfig_env(ctx), timeout=30)
    output: dict = {
        "command": " ".join(cmd),
        "returncode": result.returncode,
        "stdout": result.stdout[:8000],
        "stderr": result.stderr[:1000] if result.returncode != 0 else "",
    }
    if result.error:
        output["error"] = result.error
    return output


async def _run_argocd_app_status(args: dict, ctx: ToolContext) -> dict:
    app_name = args.get("app_name", "")
    if not app_name:
        return {"error": "argocd_app_status requires 'app_name'"}

    cmd = ["kubectl", "get", "application", app_name, "-n", "argocd", "-o", "json"]
    result = await ctx.executor.run(cmd, env=kubeconfig_env(ctx), timeout=30)

    if result.error or result.returncode != 0:
        return {
            "command": " ".join(cmd),
            "returncode": result.returncode,
            "stdout": result.stdout[:8000],
            "stderr": result.stderr[:1000],
            **({"error": result.error} if result.error else {}),
        }

    try:
        data = json.loads(result.stdout)
        status = data.get("status", {})
        return {
            "command": " ".join(cmd),
            "returncode": 0,
            "name": app_name,
            "sync_status": status.get("sync", {}).get("status"),
            "health_status": status.get("health", {}).get("status"),
            "revision": (status.get("sync", {}).get("revision") or "")[:8],
            "conditions": status.get("conditions", []),
        }
    except json.JSONDecodeError:
        return {"command": " ".join(cmd), "returncode": 0, "stdout": result.stdout[:8000]}


ARGOCD_APP_LIST_TOOL = Tool(
    name="argocd_app_list",
    description="Lists ArgoCD applications and their sync/health status (read-only).",
    parameters={
        "type": "object",
        "properties": {"namespace": {"type": "string", "description": "default: argocd"}},
    },
    execute=_run_argocd_app_list,
)

ARGOCD_APP_STATUS_TOOL = Tool(
    name="argocd_app_status",
    description="Detailed status of an ArgoCD application (sync, health, conditions) — read-only.",
    parameters={
        "type": "object",
        "properties": {"app_name": {"type": "string"}},
        "required": ["app_name"],
    },
    execute=_run_argocd_app_status,
)
