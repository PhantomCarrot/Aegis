"""
Aegis backend — self-hosted execution service.

This process runs close to the infra it controls (local or a remote
machine, see docs/execution-model.md) and talks to the Next.js frontend
through a BFF proxy authenticated by a bearer token (see
app/security/auth.py and docs/architecture.md).

M0: minimal skeleton (healthz + one protected endpoint) to validate the
Vercel(local) → proxy → token → backend chain before any business logic.
M1: multi-tenant config (see app/config/tenants.py and docs/multi-tenant.md).
M5: RAG pipeline (see app/rag/ and docs/rag.md).
M6: hardening — tightened CORS, logging, Ollama detection at startup.
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.schema import TenantConfig
from app.config.tenants import resolve_tenant
from app.logging_config import configure_logging
from app.rag.store import get_store
from app.routers import chat, health, llm, rag, tenants, tools
from app.security.auth import RequireAuth
from app.stream.ollama_provider import DEFAULT_OLLAMA_URL

configure_logging()
logger = logging.getLogger("aegis.startup")


async def _check_ollama_reachable() -> None:
    """
    Automatic Ollama detection at startup — just a log, never blocking (the
    active tenant may point to a different Ollama than the default URL,
    see docs/multi-tenant.md).
    """
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{DEFAULT_OLLAMA_URL}/api/tags")
        if resp.status_code == 200:
            n_models = len(resp.json().get("models", []))
            logger.info("Ollama detected at %s (%d models).", DEFAULT_OLLAMA_URL, n_models)
        else:
            logger.warning("Ollama responded %s at %s.", resp.status_code, DEFAULT_OLLAMA_URL)
    except Exception:
        logger.warning(
            "Ollama not detected at %s — install it (https://ollama.com) or check OLLAMA_URL.",
            DEFAULT_OLLAMA_URL,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _check_ollama_reachable()
    yield
    # Cleanly close the Qdrant client (avoids unreleased-resource warnings
    # at shutdown).
    try:
        await get_store().close()
    except Exception:
        pass


app = FastAPI(title="Aegis Backend", version="0.1.0", lifespan=lifespan)

# CORS: configurable allowlist — defaults to local dev origins (Vite/Next).
# In prod, point AEGIS_ALLOWED_ORIGINS at the real Vercel origin (see
# docs/deployment.md).
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
_allowed_origins = [o.strip() for o in os.getenv("AEGIS_ALLOWED_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(tenants.router)
app.include_router(chat.router)
app.include_router(rag.router)
app.include_router(llm.router)
app.include_router(tools.router)


@app.get("/api/ping", dependencies=[RequireAuth])
def ping(tenant: Annotated[TenantConfig, Depends(resolve_tenant)]) -> dict:
    """
    Protected test endpoint — confirms that both the bearer token *and*
    tenant resolution (X-Tenant-Id header) are verified end to end.
    """
    return {"pong": True, "tenant": {"id": tenant.id, "name": tenant.name}}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8766, reload=True)
