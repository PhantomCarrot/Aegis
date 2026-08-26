"""kubectl_get / kubectl_describe / kubectl_logs — read-only, always "safe"
(no guardrail needed, these are subcommands that never modify anything)."""
from __future__ import annotations

import shlex

from app.agent.tools.env import kubeconfig_env
from app.agent.tools.types import Tool, ToolContext


async def _run_kubectl(cmd: list[str], ctx: ToolContext, timeout: int = 30, max_stdout: int = 8000) -> dict:
    result = await ctx.executor.run(cmd, env=kubeconfig_env(ctx), timeout=timeout)
    output: dict = {
        "command": " ".join(cmd),
        "returncode": result.returncode,
        "stdout": result.stdout[:max_stdout],
        "stderr": result.stderr[:1000] if result.returncode != 0 else "",
    }
    if result.error:
        output["error"] = result.error
    return output


async def _run_kubectl_get(args: dict, ctx: ToolContext) -> dict:
    resource = args.get("resource", "")
    if not resource:
        return {"error": "kubectl_get requires 'resource'"}

    namespace = args.get("namespace", "")
    flags = args.get("flags", "")

    cmd = ["kubectl", "get", resource]
    if namespace == "all":
        cmd += ["-A"]
    elif namespace:
        cmd += ["-n", namespace]
    if flags:
        try:
            cmd += shlex.split(flags)
        except ValueError:
            cmd += flags.split()

    return await _run_kubectl(cmd, ctx)


async def _run_kubectl_describe(args: dict, ctx: ToolContext) -> dict:
    resource = args.get("resource", "")
    name = args.get("name", "")
    if not resource or not name:
        return {"error": "kubectl_describe requires 'resource' and 'name'"}

    cmd = ["kubectl", "describe", resource, name]
    if args.get("namespace"):
        cmd += ["-n", args["namespace"]]

    return await _run_kubectl(cmd, ctx)


async def _run_kubectl_logs(args: dict, ctx: ToolContext) -> dict:
    pod = args.get("pod", "")
    if not pod:
        return {"error": "kubectl_logs requires 'pod'"}

    cmd = ["kubectl", "logs", pod, f"--tail={args.get('lines', 50)}"]
    if args.get("namespace"):
        cmd += ["-n", args["namespace"]]
    if args.get("container"):
        cmd += ["-c", args["container"]]

    return await _run_kubectl(cmd, ctx)


KUBECTL_GET_TOOL = Tool(
    name="kubectl_get",
    description="kubectl get to list Kubernetes resources (read-only).",
    parameters={
        "type": "object",
        "properties": {
            "resource": {"type": "string", "description": "pods, deployments, services, nodes..."},
            "namespace": {"type": "string", "description": "namespace or 'all'"},
            "flags": {"type": "string", "description": "-o wide, --sort-by=..."},
        },
        "required": ["resource"],
    },
    execute=_run_kubectl_get,
)

KUBECTL_DESCRIBE_TOOL = Tool(
    name="kubectl_describe",
    description="kubectl describe on a specific Kubernetes resource (read-only).",
    parameters={
        "type": "object",
        "properties": {
            "resource": {"type": "string"},
            "name": {"type": "string"},
            "namespace": {"type": "string"},
        },
        "required": ["resource", "name"],
    },
    execute=_run_kubectl_describe,
)

KUBECTL_LOGS_TOOL = Tool(
    name="kubectl_logs",
    description="Logs of a Kubernetes pod (read-only).",
    parameters={
        "type": "object",
        "properties": {
            "pod": {"type": "string"},
            "namespace": {"type": "string"},
            "lines": {"type": "integer", "description": "Number of lines (default 50)"},
            "container": {"type": "string"},
        },
        "required": ["pod"],
    },
    execute=_run_kubectl_logs,
)
