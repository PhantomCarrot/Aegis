"""GET /api/tenants — list of configured tenants. GET /api/tenants/config — resolved config of the active tenant."""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.config.schema import TenantConfig
from app.config.tenants import TenantsConfigError, get_registry, resolve_tenant
from app.exec.factory import describe_executor
from app.security.auth import RequireAuth

router = APIRouter(prefix="/api", tags=["tenants"], dependencies=[RequireAuth])


@router.get("/tenants")
def list_tenants() -> dict:
    registry = get_registry()
    try:
        tenants = registry.list_tenants()
        default_id = registry.default_tenant_id
    except TenantsConfigError as e:
        # Missing/invalid config: return a usable state for the UI rather
        # than a raw 500 — the operator should be able to understand what
        # to fix without reading the backend logs.
        return {"error": str(e), "default_tenant": None, "tenants": []}

    return {
        "default_tenant": default_id,
        "tenants": [
            {"id": t.id, "name": t.name, "tools_enabled": t.tools_enabled}
            for t in tenants
        ],
    }


@router.get("/tenants/config")
def tenant_config(tenant: Annotated[TenantConfig, Depends(resolve_tenant)]) -> dict:
    """
    Resolved config (defaults + overrides already merged) of the active
    tenant — so the operator can check where commands run and where Ollama
    lives without reading config/tenants.yaml by hand. Doesn't return
    key_path (a local file path, not data that helps "check the config" in
    the sense the user means).
    """
    exec_info: dict = {"mode": tenant.exec.mode, "target": describe_executor(tenant)}
    if tenant.exec.mode == "ssh" and tenant.exec.ssh is not None:
        exec_info["host"] = tenant.exec.ssh.host
        exec_info["port"] = tenant.exec.ssh.port
        exec_info["user"] = tenant.exec.ssh.user

    # tenant.ollama.url is always used for RAG embeddings regardless of
    # llm.provider (see app/config/schema.py) — surfaced separately from
    # `llm` so it's clear which is which. See docs/llm-providers.md.
    llm_info: dict = {"provider": tenant.llm.provider}
    if tenant.llm.provider == "lmstudio":
        llm_info["url"] = tenant.llm.lmstudio.url
    elif tenant.llm.provider == "airllm" and tenant.llm.airllm is not None:
        llm_info["model"] = tenant.llm.airllm.model
        llm_info["device"] = tenant.llm.airllm.device

    return {
        "id": tenant.id,
        "name": tenant.name,
        "ollama": {"url": tenant.ollama.url},
        "llm": llm_info,
        "exec": exec_info,
        "kubeconfig_dir": tenant.kubeconfig_dir,
        "tools_enabled": tenant.tools_enabled,
        "domain_notes": tenant.domain_notes,
    }
