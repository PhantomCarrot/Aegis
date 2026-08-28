"""
"Living" documentation generation by directly scraping the infra — this is
what feeds the RAG index (no need for pre-existing external docs). This
module handles kubectl; see the sibling terraform_gen.py for Terraform
state, invoked alongside this one from the same POST /api/rag/generate
call (app/routers/rag.py). LLM-narrated doc generation isn't implemented
yet — see docs/rag.md.
"""
from __future__ import annotations

from app.agent.tools.env import kubeconfig_env
from app.agent.tools.types import ToolContext

_SECTIONS = [
    ("Namespaces", ["kubectl", "get", "ns", "--no-headers"]),
    ("Pods", ["kubectl", "get", "pods", "-A", "--no-headers"]),
    ("Deployments", ["kubectl", "get", "deployments", "-A", "--no-headers"]),
    ("Services", ["kubectl", "get", "services", "-A", "--no-headers"]),
]


async def generate_overview(ctx: ToolContext) -> str:
    """Scrapes the active tenant's cluster and returns a Markdown document ready to index."""
    env = kubeconfig_env(ctx)
    parts = [f"# Cluster Overview — {ctx.tenant.name}\n"]

    for title, cmd in _SECTIONS:
        result = await ctx.executor.run(cmd, env=env, timeout=20)
        body = result.stdout.strip() or result.stderr.strip() or result.error or "(no result)"
        parts.append(f"## {title}\n\n```\n{body}\n```\n")

    return "\n".join(parts)
