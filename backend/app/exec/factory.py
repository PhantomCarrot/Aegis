"""Resolves the executor (local or SSH) from a tenant's config."""
from __future__ import annotations

from app.config.schema import TenantConfig
from app.exec.base import CommandExecutor
from app.exec.local import LocalExecutor
from app.exec.ssh import SSHExecutor

# One SSH connection per tenant is reused across calls rather than recreated
# on every request — expensive (handshake) and unnecessary.
_ssh_executors: dict[str, SSHExecutor] = {}


def describe_executor(tenant: TenantConfig) -> str:
    """
    Human-readable description of a tenant's executor — used for
    transparency (config exposed via /api/tenants/config, and on every tool
    call result via `executed_via`, see app/agent/loop.py).
    """
    if tenant.exec.mode == "ssh" and tenant.exec.ssh is not None:
        ssh = tenant.exec.ssh
        return f"ssh://{ssh.user}@{ssh.host}:{ssh.port}"
    return "local"


def get_executor(tenant: TenantConfig) -> CommandExecutor:
    if tenant.exec.mode == "local":
        return LocalExecutor()

    if tenant.exec.mode == "ssh":
        assert tenant.exec.ssh is not None  # guaranteed by pydantic validation
        if tenant.id not in _ssh_executors:
            _ssh_executors[tenant.id] = SSHExecutor(tenant.exec.ssh)
        return _ssh_executors[tenant.id]

    raise ValueError(f"Unknown exec.mode for tenant '{tenant.id}': {tenant.exec.mode}")
