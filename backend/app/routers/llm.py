"""GET /api/llm/models — models available on the active tenant's LLM provider
(Ollama, LM Studio, or AirLLM — see docs/llm-providers.md)."""
from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends

from app.config.schema import TenantConfig
from app.config.tenants import resolve_tenant
from app.security.auth import RequireAuth

router = APIRouter(prefix="/api/llm", tags=["llm"], dependencies=[RequireAuth])


@router.get("/models")
async def list_models(tenant: Annotated[TenantConfig, Depends(resolve_tenant)]) -> dict:
    """
    Model discovery is per-provider — Ollama and LM Studio both expose a
    models endpoint to query live, AirLLM doesn't (its model is a fixed
    part of the tenant config, not something to pick at runtime). See
    docs/llm-providers.md.
    """
    provider = tenant.llm.provider

    if provider == "ollama":
        return await _list_ollama_models(tenant.ollama.url)

    if provider == "lmstudio":
        return await _list_lmstudio_models(tenant.llm.lmstudio.url)

    if provider == "airllm":
        assert tenant.llm.airllm is not None  # guaranteed by pydantic validation
        return {"provider": "airllm", "models": [tenant.llm.airllm.model]}

    return {"provider": provider, "models": [], "error": f"Unknown provider: {provider}"}  # pragma: no cover


async def _list_ollama_models(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/api/tags")
        resp.raise_for_status()
        data = resp.json()
        models = sorted(m["name"] for m in data.get("models", []))
        return {"provider": "ollama", "models": models, "ollama_url": url}
    except Exception as e:
        return {"provider": "ollama", "models": [], "ollama_url": url, "error": str(e)}


async def _list_lmstudio_models(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{url}/v1/models")
        resp.raise_for_status()
        data = resp.json()
        models = sorted(m["id"] for m in data.get("data", []))
        return {"provider": "lmstudio", "models": models, "lmstudio_url": url}
    except Exception as e:
        return {"provider": "lmstudio", "models": [], "lmstudio_url": url, "error": str(e)}
