"""POST /api/rag/generate, GET /api/rag/status — RAG pipeline. See docs/rag.md."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agent.tools.registry import ToolContext
from app.config.schema import TenantConfig
from app.config.tenants import resolve_tenant
from app.exec.factory import describe_executor, get_executor
from app.rag import docs_gen
from app.rag.embeddings import EmbeddingError
from app.rag.indexer import index_text
from app.rag.store import get_store
from app.security.auth import RequireAuth

router = APIRouter(prefix="/api/rag", tags=["rag"], dependencies=[RequireAuth])

_OVERVIEW_SOURCE_PATH = "cluster-overview.md"


@router.post("/generate")
async def generate(tenant: Annotated[TenantConfig, Depends(resolve_tenant)]) -> dict:
    """Scrapes the active tenant's cluster, writes a Markdown doc, and indexes it."""
    ctx = ToolContext(tenant=tenant, executor=get_executor(tenant), exec_target=describe_executor(tenant))
    markdown = await docs_gen.generate_overview(ctx)

    try:
        chunks_indexed = await index_text(tenant, get_store(), _OVERVIEW_SOURCE_PATH, markdown)
    except EmbeddingError as e:
        return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "source_path": _OVERVIEW_SOURCE_PATH,
        "chunks_indexed": chunks_indexed,
        "chars": len(markdown),
    }


@router.get("/status")
async def status(tenant: Annotated[TenantConfig, Depends(resolve_tenant)]) -> dict:
    return await get_store().status(tenant.id)


@router.get("/documents")
async def documents(tenant: Annotated[TenantConfig, Depends(resolve_tenant)]) -> dict:
    """
    Indexed content for the active tenant, grouped by source document — to
    inspect what actually feeds RAG mode, not just the chunk count. See
    docs/rag.md.
    """
    chunks = await get_store().list_chunks(tenant.id)

    grouped: dict[str, list[dict]] = {}
    for c in chunks:
        grouped.setdefault(c["source_path"], []).append(c)
    for source_chunks in grouped.values():
        source_chunks.sort(key=lambda c: c["chunk_index"])

    return {
        "documents": [
            {"source_path": path, "chunk_count": len(source_chunks), "chunks": source_chunks}
            for path, source_chunks in sorted(grouped.items())
        ]
    }
