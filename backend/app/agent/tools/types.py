"""Types shared by all tool modules — avoids circular imports between
registry.py and the individual tools (kubectl.py, etc.)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from app.agent.guardrails import Classification
from app.config.schema import TenantConfig
from app.exec.base import CommandExecutor


@dataclass
class ToolContext:
    tenant: TenantConfig
    executor: CommandExecutor
    # Human-readable description of the executor ("local" or
    # "ssh://user@host:port") — reported in tool call results
    # (`executed_via`, see loop.py) so the operator can see where each
    # command actually ran.
    exec_target: str = "local"


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema — passed as-is to Ollama tool-calling
    execute: Callable[[dict, ToolContext], Awaitable[dict]]
    # None = tool is always "safe" (structured read-only, e.g. kubectl_get)
    # — never subject to guardrails. Otherwise, a function that determines
    # the classification from the arguments (e.g. run_command classifies
    # the shell command it's given) — see app/agent/guardrails.py and the
    # branching in app/agent/loop.py.
    classify: Callable[[dict], Classification] | None = None
