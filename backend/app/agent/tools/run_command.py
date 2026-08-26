"""
run_command — arbitrary shell command (pipes, redirections supported).

Unlike kubectl_get, this tool isn't structurally safe: its classification
(safe/mutant/destructive) is determined dynamically from the command
provided by the LLM — see app/agent/guardrails.py and the branching in
app/agent/loop.py.
"""
from __future__ import annotations

from app.agent.guardrails import Classification, classify_command
from app.agent.tools.env import kubeconfig_env
from app.agent.tools.types import Tool, ToolContext


def _classify(args: dict) -> Classification:
    return classify_command(args.get("command", ""))


async def _run_command(args: dict, ctx: ToolContext) -> dict:
    command = args.get("command", "")
    if not command:
        return {"error": "run_command requires 'command'"}

    result = await ctx.executor.run(command, env=kubeconfig_env(ctx), timeout=60, shell=True)
    output: dict = {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout[:8000],
        "stderr": result.stderr[:1000] if result.returncode != 0 else "",
    }
    if result.error:
        output["error"] = result.error
    return output


RUN_COMMAND_TOOL = Tool(
    name="run_command",
    description=(
        "Arbitrary shell command with pipe/redirection support. Use this "
        "tool for anything that doesn't have a dedicated tool — commands "
        "that modify or delete resources require confirmation."
    ),
    parameters={
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    execute=_run_command,
    classify=_classify,
)
