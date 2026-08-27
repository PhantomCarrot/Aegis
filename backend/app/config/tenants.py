"""
Loading + hot-reload of the multi-tenant config.

Two files watched independently (mtime comparison on every access — no
watcher, near-zero cost):
- config/global.yaml   → optional, Python defaults if absent
- config/tenants.yaml  → required, the list of tenants

Editing either one takes effect immediately, without restarting the
process — see docs/multi-tenant.md.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import yaml
from fastapi import Header, HTTPException
from pydantic import ValidationError

from app.config.schema import GlobalConfig, TenantConfig, TenantsFile

def _default_global_path() -> Path:
    # Read on each call rather than at module load time: otherwise a test
    # that does monkeypatch.setenv(...) after the first import would never
    # be picked up (the module doesn't reload between tests).
    return Path(os.getenv("AEGIS_GLOBAL_CONFIG_FILE", "config/global.yaml"))


def _default_tenants_path() -> Path:
    return Path(os.getenv("AEGIS_TENANTS_FILE", "config/tenants.yaml"))


class TenantsConfigError(Exception):
    """Invalid config — fail-fast error with a clear message (not a silent yaml.safe_load)."""


class TenantNotFoundError(Exception):
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        super().__init__(f"Unknown tenant: {tenant_id!r}")


def deep_merge(base: dict, override: dict) -> dict:
    """Recursive dict merge, override wins per leaf key — only recurses into
    nested dicts. Shared with app/config/writer.py, which validates a
    tenant's merged config the same way before writing it to disk."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_global_config(path: Path) -> GlobalConfig:
    """global.yaml is optional — absence = Python defaults, not an error.
    Shared with app/config/writer.py."""
    if not path.exists():
        return GlobalConfig()
    try:
        raw_global = yaml.safe_load(path.read_text()) or {}
        return GlobalConfig.model_validate(raw_global)
    except (yaml.YAMLError, ValidationError) as e:
        raise TenantsConfigError(f"Invalid config in {path}: {e}") from e


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


class TenantRegistry:
    """
    Keeps resolved tenants in memory; `_ensure_fresh()` reloads from disk
    if either file has changed since the last access.
    """

    def __init__(
        self,
        global_path: Path | None = None,
        tenants_path: Path | None = None,
    ):
        self._global_path = global_path if global_path is not None else _default_global_path()
        self._tenants_path = tenants_path if tenants_path is not None else _default_tenants_path()
        self._lock = threading.Lock()
        self._global_mtime: float | None = None
        self._tenants_mtime: float | None = None
        self._default_tenant: str | None = None
        self._tenants: dict[str, TenantConfig] = {}
        self._loaded_once = False

    def _load(self) -> None:
        global_cfg = load_global_config(self._global_path)

        if not self._tenants_path.exists():
            raise TenantsConfigError(
                f"Config file not found: {self._tenants_path}. "
                f"Copy config/tenants.yaml.example to config/tenants.yaml to get started."
            )

        try:
            raw_tenants = yaml.safe_load(self._tenants_path.read_text()) or {}
            tenants_file = TenantsFile.model_validate(raw_tenants)
        except (yaml.YAMLError, ValidationError) as e:
            raise TenantsConfigError(f"Invalid config in {self._tenants_path}: {e}") from e

        defaults_dict = global_cfg.model_dump()
        tenants: dict[str, TenantConfig] = {}
        for tenant_id, raw_tenant in tenants_file.tenants.items():
            merged = deep_merge(defaults_dict, raw_tenant)
            merged["id"] = tenant_id
            try:
                tenants[tenant_id] = TenantConfig.model_validate(merged)
            except ValidationError as e:
                raise TenantsConfigError(
                    f"Invalid tenant '{tenant_id}' in {self._tenants_path}: {e}"
                ) from e

        if tenants_file.default_tenant not in tenants:
            raise TenantsConfigError(
                f"default_tenant '{tenants_file.default_tenant}' not found among the tenants "
                f"defined in {self._tenants_path} ({', '.join(tenants) or 'none'})."
            )

        self._tenants = tenants
        self._default_tenant = tenants_file.default_tenant
        self._global_mtime = _mtime(self._global_path)
        self._tenants_mtime = _mtime(self._tenants_path)
        self._loaded_once = True

    def _ensure_fresh(self) -> None:
        with self._lock:
            changed = (
                not self._loaded_once
                or _mtime(self._global_path) != self._global_mtime
                or _mtime(self._tenants_path) != self._tenants_mtime
            )
            if changed:
                self._load()

    def list_tenants(self) -> list[TenantConfig]:
        self._ensure_fresh()
        return list(self._tenants.values())

    def get(self, tenant_id: str) -> TenantConfig:
        self._ensure_fresh()
        if tenant_id not in self._tenants:
            raise TenantNotFoundError(tenant_id)
        return self._tenants[tenant_id]

    @property
    def default_tenant_id(self) -> str:
        self._ensure_fresh()
        assert self._default_tenant is not None
        return self._default_tenant


_registry: TenantRegistry | None = None


def get_registry() -> TenantRegistry:
    global _registry
    if _registry is None:
        _registry = TenantRegistry()
    return _registry


def reset_registry() -> None:
    """Used by tests to start each case with a clean registry."""
    global _registry
    _registry = None


def resolve_tenant(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
) -> TenantConfig:
    """
    FastAPI dependency: determines the active tenant for the current request.

    No mutable global state server-side — the active tenant is carried by
    each request (a header sent by the frontend, persisted client-side in
    localStorage). Falls back to the default tenant if the header is absent.
    """
    registry = get_registry()
    try:
        tenant_id = x_tenant_id or registry.default_tenant_id
        return registry.get(tenant_id)
    except TenantNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except TenantsConfigError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
