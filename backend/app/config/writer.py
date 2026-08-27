"""
Writes config/tenants.yaml — the persistence side of tenant administration
(create/edit/delete a tenant from the UI instead of hand-editing YAML).

Uses ruamel.yaml in round-trip mode rather than plain PyYAML: hand-written
tenants.yaml files carry real operational comments (sometimes 10+ lines per
tenant), and a plain yaml.safe_load()/yaml.safe_dump() round trip would
silently strip every comment in the file the first time anyone saves through
the UI — including comments on tenants the UI never touched. Round-trip mode
keeps every untouched tenant's node exactly as it was on disk; only the
tenant actually being written is replaced wholesale (so that tenant's own
comments don't survive its own edit — an accepted tradeoff, see the plan).

Every write is validated against the schema (deep-merged with global.yaml's
defaults, exactly like app/config/tenants.py resolves a tenant at read time)
*before* touching disk, and written atomically (temp file + os.replace) so a
concurrent hot-reload in TenantRegistry never observes a half-written file.

Single-process assumption: `_write_lock` is an in-process threading.Lock,
which only serializes writers within one uvicorn worker. If Aegis ever runs
multiple backend processes against the same tenants.yaml, this needs a real
file lock (e.g. fcntl.flock) instead — out of scope today.
"""
from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from app.config.schema import TenantConfig
from app.config.tenants import (
    _default_global_path,
    _default_tenants_path,
    deep_merge,
    load_global_config,
)

_write_lock = threading.Lock()


class TenantWriteError(Exception):
    """Base for every error writer.py can raise — the router maps these to HTTP status codes."""


class TenantAlreadyExistsError(TenantWriteError):
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        super().__init__(f"Tenant already exists: {tenant_id!r}")


class TenantMissingError(TenantWriteError):
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        super().__init__(f"Unknown tenant: {tenant_id!r}")


class TenantValidationError(TenantWriteError):
    def __init__(self, tenant_id: str, errors: ValidationError):
        self.tenant_id = tenant_id
        self.errors = errors
        super().__init__(f"Invalid config for tenant {tenant_id!r}: {errors}")


class CannotDeleteDefaultTenantError(TenantWriteError):
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        super().__init__(
            f"{tenant_id!r} is the default tenant — set a different default "
            "first (PUT /api/tenants/default), then delete it."
        )


class CannotDeleteLastTenantError(TenantWriteError):
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        super().__init__(f"Can't delete {tenant_id!r} — it's the only tenant left.")


def _yaml() -> YAML:
    y = YAML()  # round-trip mode by default — preserves comments/formatting
    y.preserve_quotes = True
    y.width = 4096  # don't wrap long lines (URLs, paths) mid-value
    return y


def _load_doc(tenants_path: Path) -> CommentedMap:
    y = _yaml()
    if tenants_path.exists():
        with tenants_path.open("r") as f:
            doc = y.load(f)
        if doc is None:
            doc = CommentedMap()
    else:
        doc = CommentedMap()
    if doc.get("tenants") is None:
        doc["tenants"] = CommentedMap()
    if "default_tenant" not in doc:
        doc["default_tenant"] = None
    return doc


def _write_atomic(doc: CommentedMap, tenants_path: Path) -> None:
    tenants_path.parent.mkdir(parents=True, exist_ok=True)
    y = _yaml()
    fd, tmp_path = tempfile.mkstemp(dir=tenants_path.parent, prefix=".tenants-", suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            y.dump(doc, f)
        os.replace(tmp_path, tenants_path)
    except BaseException:
        # os.replace didn't happen (or dump failed) — clean up the temp file
        # rather than leaving stray .tmp files around on every error.
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _validate_merged(tenant_id: str, override: dict, global_path: Path) -> TenantConfig:
    global_cfg = load_global_config(global_path)
    merged = deep_merge(global_cfg.model_dump(), override)
    merged["id"] = tenant_id
    try:
        return TenantConfig.model_validate(merged)
    except ValidationError as e:
        raise TenantValidationError(tenant_id, e) from e


def create_tenant(
    tenant_id: str,
    override: dict,
    *,
    tenants_path: Path | None = None,
    global_path: Path | None = None,
) -> TenantConfig:
    tenants_path = tenants_path if tenants_path is not None else _default_tenants_path()
    global_path = global_path if global_path is not None else _default_global_path()

    with _write_lock:
        doc = _load_doc(tenants_path)
        if tenant_id in doc["tenants"]:
            raise TenantAlreadyExistsError(tenant_id)

        resolved = _validate_merged(tenant_id, override, global_path)

        doc["tenants"][tenant_id] = override
        # Bootstrap case: file was empty/nonexistent, or default_tenant was
        # never set — the first tenant created becomes the default so the
        # file stays valid (TenantsFile requires default_tenant to resolve).
        if not doc.get("default_tenant"):
            doc["default_tenant"] = tenant_id
        _write_atomic(doc, tenants_path)
        return resolved


def update_tenant(
    tenant_id: str,
    override: dict,
    *,
    tenants_path: Path | None = None,
    global_path: Path | None = None,
) -> TenantConfig:
    tenants_path = tenants_path if tenants_path is not None else _default_tenants_path()
    global_path = global_path if global_path is not None else _default_global_path()

    with _write_lock:
        doc = _load_doc(tenants_path)
        if tenant_id not in doc["tenants"]:
            raise TenantMissingError(tenant_id)

        resolved = _validate_merged(tenant_id, override, global_path)

        # Wholesale replace of this tenant's node — simple and correct, at
        # the cost of dropping any comments that lived specifically inside
        # this tenant's own block. Every OTHER tenant's node is untouched.
        doc["tenants"][tenant_id] = override
        _write_atomic(doc, tenants_path)
        return resolved


def delete_tenant(
    tenant_id: str,
    *,
    tenants_path: Path | None = None,
) -> None:
    tenants_path = tenants_path if tenants_path is not None else _default_tenants_path()

    with _write_lock:
        doc = _load_doc(tenants_path)
        if tenant_id not in doc["tenants"]:
            raise TenantMissingError(tenant_id)
        if doc.get("default_tenant") == tenant_id:
            raise CannotDeleteDefaultTenantError(tenant_id)
        if len(doc["tenants"]) <= 1:
            raise CannotDeleteLastTenantError(tenant_id)

        del doc["tenants"][tenant_id]
        _write_atomic(doc, tenants_path)


def set_default_tenant(
    tenant_id: str,
    *,
    tenants_path: Path | None = None,
) -> None:
    tenants_path = tenants_path if tenants_path is not None else _default_tenants_path()

    with _write_lock:
        doc = _load_doc(tenants_path)
        if tenant_id not in doc["tenants"]:
            raise TenantMissingError(tenant_id)
        doc["default_tenant"] = tenant_id
        _write_atomic(doc, tenants_path)
