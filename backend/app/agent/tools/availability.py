"""
Checks whether a tool group's underlying CLI binary is actually runnable
at a tenant's resolved executor (local subprocess or SSH host) — GET
/api/tools surfaces this per tool so ToolsPanel.tsx can show a disabled +
warning state distinct from "not allowed by tenant config" (`enabled`).
See docs/tools.md.

Deliberately generic: probes via `command -v {binary}` (POSIX, identical
under LocalExecutor and SSHExecutor since both ultimately shell out)
rather than a tool-specific "version" flag per binary — no per-CLI
invocation syntax hardcoded here, reusable as-is for any future tool.
"""
from __future__ import annotations

import shlex
import time

from app.agent.tools.cloud_providers import get_cloud_provider
from app.agent.tools.registry import tool_group
from app.config.schema import TenantConfig
from app.exec.base import CommandExecutor

# Short and independent of the 30s default tool-call timeout — a slow or
# unreachable SSH host must never make GET /api/tools hang.
_PROBE_TIMEOUT = 5
_CACHE_TTL = 60  # seconds — avoids re-probing on every panel open/render

# Static binary each group needs. None = not statically checkable, never
# probed, always reported available. argocd tools actually run through
# `kubectl get applications` (see agent/tools/argocd.py), not the `argocd`
# CLI — checking for an "argocd" binary would test the wrong thing.
# "cloud_cli" is deliberately absent here — its binary depends on the
# tenant's configured provider, resolved dynamically below.
_GROUP_REQUIRED_BINARY: dict[str, str | None] = {
    "kubectl": "kubectl",
    "argocd": "kubectl",
    "run_command": None,
}

_cache: dict[tuple[str, str], tuple[bool, str | None, float]] = {}


def reset_cache() -> None:
    """Used by tests to start each case with a clean cache."""
    _cache.clear()


def _required_binary(tenant: TenantConfig, group: str) -> str | None:
    if group == "cloud_cli":
        return get_cloud_provider(tenant).binary
    return _GROUP_REQUIRED_BINARY.get(group)


async def binary_available(executor: CommandExecutor, binary: str) -> tuple[bool, str | None]:
    """`command` is a shell builtin, not an executable — this must go
    through the shell (shell=True), not be exec()'d directly."""
    result = await executor.run(f"command -v {shlex.quote(binary)}", timeout=_PROBE_TIMEOUT, shell=True)
    if result.error:
        return False, result.error
    if result.returncode != 0:
        return False, f"'{binary}' not found"
    return True, None


async def _cached_binary_available(tenant_id: str, executor: CommandExecutor, binary: str) -> tuple[bool, str | None]:
    key = (tenant_id, binary)
    cached = _cache.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[2] < _CACHE_TTL:
        return cached[0], cached[1]
    available, reason = await binary_available(executor, binary)
    _cache[key] = (available, reason, now)
    return available, reason


async def tools_availability(
    tenant: TenantConfig, executor: CommandExecutor, tool_names: list[str]
) -> dict[str, bool]:
    """One availability check per distinct required binary (cached), mapped
    back to every tool name that depends on it."""
    result: dict[str, bool] = {}
    for name in tool_names:
        group = tool_group(name)
        binary = _required_binary(tenant, group) if group else None
        if binary is None:
            result[name] = True
            continue
        available, _reason = await _cached_binary_available(tenant.id, executor, binary)
        result[name] = available
    return result
