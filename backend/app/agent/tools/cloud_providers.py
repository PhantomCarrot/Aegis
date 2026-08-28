"""
Resolves which cloud CLI grammar answers cloud_cli calls for a given
tenant, from `tenant.cloud_provider` (see app/config/schema.py). Every
provider module (azure_cli.py, ...) exposes the same shape — `BINARY`,
`validate_action(action) -> str | None`, `build_command(resource_type,
action, extra, fmt) -> list[str]` — so cloud_cli.py never needs to know
which one it's talking to; it just calls whatever this returns. Mirrors
app/stream/providers.py's dispatch for LLM providers exactly, same
reasoning. See docs/tools.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.agent.tools import azure_cli
from app.config.schema import TenantConfig


@dataclass
class CloudCliProvider:
    binary: str
    validate_action: Callable[[str], str | None]
    build_command: Callable[[str, str, dict, str], list[str]]


def get_cloud_provider(tenant: TenantConfig) -> CloudCliProvider:
    if tenant.cloud_provider == "az":
        return CloudCliProvider(azure_cli.BINARY, azure_cli.validate_action, azure_cli.build_command)

    raise ValueError(f"Unknown cloud_provider for tenant '{tenant.id}': {tenant.cloud_provider!r}")  # pragma: no cover
