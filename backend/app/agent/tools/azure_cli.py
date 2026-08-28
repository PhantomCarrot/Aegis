"""
Azure CLI grammar for cloud_cli.py — the only cloud_cli provider actually
implemented today. Everything specific to `az`'s command shape lives here:
its binary name, its `list/show/get/describe` action grammar, how a
command is built. A future AWS/GCP provider gets its own sibling module
with its own `validate_action`/`build_command` — AWS's compound verbs
(`describe-instances`, `list-buckets`) don't fit this same allowed-actions
set, so nothing here is meant to be shared, only the shape (see
app/agent/tools/cloud_providers.py). See docs/tools.md.
"""
from __future__ import annotations

import shlex

BINARY = "az"

_ALLOWED_ACTIONS = {"list", "show", "get", "describe"}

TOOL_DESCRIPTION = (
    "Queries cloud resources — Azure (az CLI) in V1. Read-only: "
    "list/show/get/describe only. Examples: resource_type='keyvault secret', "
    "action='list', args={'--vault-name': 'my-kv'} ; resource_type='aks', action='list' ; "
    "resource_type='storage account', action='list'."
)


def validate_action(action: str) -> str | None:
    """Returns an error message, or None if the action is allowed."""
    if action not in _ALLOWED_ACTIONS:
        return f"Action '{action}' not allowed — read-only (list/show/get/describe)"
    return None


def build_command(resource_type: str, action: str, extra: dict, fmt: str) -> list[str]:
    cmd = [BINARY] + shlex.split(resource_type) + [action]
    for k, v in extra.items():
        cmd += [str(k), str(v)]
    return cmd + ["-o", fmt]
