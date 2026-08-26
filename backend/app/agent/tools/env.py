"""Environment shared by tools that talk to Kubernetes."""
from __future__ import annotations

import os
from pathlib import Path

from app.agent.tools.types import ToolContext


def kubeconfig_env(ctx: ToolContext) -> dict | None:
    """
    For local execution: KUBECONFIG is always explicit, built from
    `tenant.kubeconfig_dir`, never inherited from the backend process's
    ambient environment — a tenant must never be able to, even
    accidentally, reach another tenant's cluster (or the operator's) via a
    KUBECONFIG inherited from the shell that launched the backend.

    For SSH execution: returns None (no env override sent over the SSH
    session) — `tenant.kubeconfig_dir` names a path on *this* machine,
    meaningless on the remote host. The tenant is expected to have its own
    default kubectl setup there (e.g. a system-wide ~/.kube/config) —
    there's no equivalent of `kubeconfig_dir` for a path on the remote
    side yet. See docs/execution-model.md.
    """
    if ctx.tenant.exec.mode != "local":
        return None
    env = dict(os.environ)
    kube_dir = Path(os.path.expanduser(ctx.tenant.kubeconfig_dir))
    files = sorted(kube_dir.glob("*.yaml")) if kube_dir.exists() else []
    if files:
        env["KUBECONFIG"] = ":".join(str(f) for f in files)
    else:
        # No kubeconfig for this tenant → point to a nonexistent path
        # rather than letting kubectl fall back to the ambient KUBECONFIG.
        env["KUBECONFIG"] = str(kube_dir / "none.yaml")
    return env
