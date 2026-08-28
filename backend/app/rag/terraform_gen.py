"""
Scrapes Terraform state into a Markdown document ready to index — the
sibling of docs_gen.py (kubectl), invoked from the same
POST /api/rag/generate call when the tenant has `terraform_dir`
configured. Never raises: a scrape failure (terraform not installed,
never applied, wrong directory) lands as visible text in the doc instead
of aborting generate() entirely — same philosophy as docs_gen.py. See
docs/rag.md.
"""
from __future__ import annotations

import json
import os

from app.agent.tools.types import ToolContext

_TIMEOUT = 30


def _iter_resources(module: dict):
    """Recurses into Terraform's `values.root_module` shape — modules
    nest arbitrarily deep via `child_modules`, each the same shape."""
    for resource in module.get("resources", []):
        yield resource
    for child in module.get("child_modules", []):
        yield from _iter_resources(child)


async def generate_terraform_overview(ctx: ToolContext) -> str | None:
    """Returns None (skip indexing) if the tenant has no terraform_dir configured."""
    terraform_dir = ctx.tenant.terraform_dir
    if not terraform_dir:
        return None

    # `cd {dir} && terraform show -json` as a single shell string, not a
    # cwd parameter — CommandExecutor has no such parameter (base.py,
    # local.py, ssh.py), and SSHExecutor always collapses a command to one
    # shell string regardless of the `shell` flag anyway (see ssh.py), so
    # this is the only approach that works identically under both
    # executors without touching any of the three. Same precedent as
    # run_command.py's own shell=True raw-string usage.
    #
    # Local mode: expand `~` against *this* machine before interpolating
    # (the command also runs on this machine). SSH mode: leave it as
    # written — the remote shell expands its own `~`, same asymmetry
    # kubeconfig_env() already has for kubeconfig_dir (no equivalent path
    # translation for the remote side today, see agent/tools/env.py).
    #
    # Not shlex.quote()'d: quoting would single-quote the path, and no
    # POSIX shell expands `~` inside single quotes — that would silently
    # break the common `terraform_dir: "~/infra/terraform"` style already
    # used for kubeconfig_dir/key_path elsewhere. terraform_dir is trusted
    # operator config, same trust tier as ssh.host/key_path — interpolated
    # raw, like run_command's own LLM-provided string.
    if ctx.tenant.exec.mode == "local":
        terraform_dir = os.path.expanduser(terraform_dir)
    command = f"cd {terraform_dir} && terraform show -json"

    result = await ctx.executor.run(command, timeout=_TIMEOUT, shell=True)

    parts = [f"# Terraform State — {ctx.tenant.name}\n"]

    if result.returncode != 0 or result.error:
        body = result.stdout.strip() or result.stderr.strip() or result.error or "(no result)"
        parts.append(f"## Error\n\n```\n{body}\n```\n")
        return "\n".join(parts)

    try:
        state = json.loads(result.stdout)
    except json.JSONDecodeError:
        parts.append(f"## Error\n\nNot valid JSON:\n\n```\n{result.stdout[:2000]}\n```\n")
        return "\n".join(parts)

    root_module = state.get("values", {}).get("root_module", {})
    resources = list(_iter_resources(root_module))
    if not resources:
        parts.append("(no resources found)\n")
        return "\n".join(parts)

    for resource in resources:
        address = resource.get("address", "(unknown address)")
        mode = resource.get("mode", "?")
        provider_name = resource.get("provider_name", "?")
        values = json.dumps(resource.get("values", {}), indent=2, sort_keys=True)
        parts.append(
            f"## {address}\n\n"
            f"- **Type**: {resource.get('type', '?')} ({mode})\n"
            f"- **Provider**: {provider_name}\n\n"
            f"```json\n{values}\n```\n"
        )

    return "\n".join(parts)
