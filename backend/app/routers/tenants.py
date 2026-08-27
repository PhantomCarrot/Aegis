"""
GET /api/tenants — list of configured tenants.
GET /api/tenants/config — resolved config of the active tenant (redacted).
GET/POST/PUT/DELETE /api/tenants/{id}, PUT /api/tenants/default — tenant
administration: create/edit/delete a tenant from the UI instead of
hand-editing config/tenants.yaml. See app/config/writer.py for the actual
read-modify-write logic; this router only translates HTTP <-> writer.py.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import writer
from app.config.schema import ExecConfig, LLMConfig, OllamaConfig, TenantConfig
from app.config.tenants import TenantNotFoundError, TenantsConfigError, get_registry, resolve_tenant
from app.exec.factory import describe_executor
from app.security.auth import RequireAuth

router = APIRouter(prefix="/api", tags=["tenants"], dependencies=[RequireAuth])

# DNS-label-like: safe as a URL path segment, a YAML mapping key, and a
# filesystem path component (it becomes part of the default kubeconfig_dir).
_TENANT_ID_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"


class TenantWriteRequest(BaseModel):
    """Body for PUT /api/tenants/{id} (update). Every field is what the
    caller wants this tenant's config to be; omitting ollama/llm/exec means
    "inherit from global.yaml" (matches how config/tenants.yaml itself
    works) — the tenant-admin UI happens to always send them explicitly."""

    model_config = ConfigDict(extra="forbid")

    name: str
    ollama: OllamaConfig | None = None
    llm: LLMConfig | None = None
    exec: ExecConfig | None = None
    kubeconfig_dir: str = ""
    tools_enabled: list[str] = Field(default_factory=list)
    domain_notes: str = ""


class TenantCreateRequest(TenantWriteRequest):
    """Body for POST /api/tenants (create) — same as an update, plus the new tenant's id."""

    id: str = Field(pattern=_TENANT_ID_PATTERN)


class SetDefaultTenantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str


def _map_write_error(e: writer.TenantWriteError) -> HTTPException:
    if isinstance(e, writer.TenantAlreadyExistsError):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, writer.TenantMissingError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, writer.TenantValidationError):
        return HTTPException(status_code=422, detail=str(e))
    # CannotDeleteDefaultTenantError, CannotDeleteLastTenantError, and any
    # future TenantWriteError subclass we haven't special-cased — all are
    # "the request itself is the problem", not a server error.
    return HTTPException(status_code=400, detail=str(e))


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


@router.post("/tenants", status_code=201)
def create_tenant(body: TenantCreateRequest) -> dict:
    """Create a new tenant. 409 if the id already exists, 422 if the
    resulting config fails schema validation — the file on disk is
    unchanged in that case (validated before writing, see writer.py)."""
    override = body.model_dump(exclude_none=True, exclude={"id"})
    try:
        resolved = writer.create_tenant(body.id, override)
    except writer.TenantWriteError as e:
        raise _map_write_error(e) from e
    return resolved.model_dump()


# Declared before GET /tenants/{tenant_id}: FastAPI matches routes in
# registration order, so the literal "/tenants/config" path must come first
# or {tenant_id} would swallow "config" as if it were a tenant id.
@router.put("/tenants/default")
def set_default_tenant(body: SetDefaultTenantRequest) -> dict:
    """Change which tenant is the default (used when no X-Tenant-Id header
    is sent). The only way to unblock deleting the current default — see
    CannotDeleteDefaultTenantError in writer.py."""
    try:
        writer.set_default_tenant(body.tenant_id)
    except writer.TenantWriteError as e:
        raise _map_write_error(e) from e
    return {"ok": True}


@router.get("/tenants/{tenant_id}")
def tenant_full_config(tenant_id: str) -> dict:
    """
    Full resolved config of ANY tenant (not just the active one, unlike
    GET /tenants/config), including key_path/certificate_path/
    known_hosts_path — GET /tenants/config deliberately omits those for the
    read-only summary view, but the tenant-admin UI needs them to pre-fill
    an edit form.
    """
    registry = get_registry()
    try:
        tenant = registry.get(tenant_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except TenantsConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return tenant.model_dump()


@router.put("/tenants/{tenant_id}")
def update_tenant(tenant_id: str, body: TenantWriteRequest) -> dict:
    """Replace a tenant's config wholesale. 404 if unknown, 422 if the
    resulting config fails schema validation (file unchanged in that case)."""
    override = body.model_dump(exclude_none=True)
    try:
        resolved = writer.update_tenant(tenant_id, override)
    except writer.TenantWriteError as e:
        raise _map_write_error(e) from e
    return resolved.model_dump()


@router.delete("/tenants/{tenant_id}")
def delete_tenant(tenant_id: str) -> dict:
    """404 if unknown. 400 if it's the current default tenant (set a
    different default first, PUT /tenants/default) or the last tenant left."""
    try:
        writer.delete_tenant(tenant_id)
    except writer.TenantWriteError as e:
        raise _map_write_error(e) from e
    return {"ok": True}
