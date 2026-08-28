"""POST /api/rag/generate, GET /api/rag/status — RAG pipeline. See docs/rag.md."""
from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends

from app.agent.tools.registry import ToolContext
from app.config.schema import TenantConfig
from app.config.tenants import resolve_tenant
from app.exec.factory import describe_executor, get_executor
from app.logging_config import get_audit_logger
from app.rag import docs_gen, terraform_gen
from app.rag.embeddings import EmbeddingError
from app.rag.indexer import index_text
from app.rag.store import get_store
from app.security.auth import RequireAuth

router = APIRouter(prefix="/api/rag", tags=["rag"], dependencies=[RequireAuth])

_KUBECTL_SOURCE_PATH = "cluster-overview.md"
_TERRAFORM_SOURCE_PATH = "terraform-state.md"

_audit = get_audit_logger()


@router.post("/generate")
async def generate(tenant: Annotated[TenantConfig, Depends(resolve_tenant)]) -> dict:
    """
    Scrapes the active tenant's infra and indexes it — kubectl always,
    plus Terraform state if `tenant.terraform_dir` is configured. Each
    scrape becomes its own document (distinct source_path), so
    GET /api/rag/documents lists them separately.
    """
    started = time.monotonic()
    ctx = ToolContext(tenant=tenant, executor=get_executor(tenant), exec_target=describe_executor(tenant))
    store = get_store()

    to_index = [(_KUBECTL_SOURCE_PATH, await docs_gen.generate_overview(ctx))]
    terraform_markdown = await terraform_gen.generate_terraform_overview(ctx)
    if terraform_markdown is not None:
        to_index.append((_TERRAFORM_SOURCE_PATH, terraform_markdown))

    documents = []
    try:
        for source_path, markdown in to_index:
            chunks_indexed, generated_at = await index_text(tenant, store, source_path, markdown)
            documents.append({
                "source_path": source_path,
                "chunks_indexed": chunks_indexed,
                "chars": len(markdown),
                "generated_at": generated_at,
            })
    except EmbeddingError as e:
        duration_ms = round((time.monotonic() - started) * 1000)
        _audit.info(
            "rag_generate tenant=%s ok=%s documents=0 chunks_indexed=0 duration_ms=%d",
            tenant.id, False, duration_ms,
        )
        return {"ok": False, "error": str(e)}

    duration_ms = round((time.monotonic() - started) * 1000)
    total_chunks = sum(d["chunks_indexed"] for d in documents)
    _audit.info(
        "rag_generate tenant=%s ok=%s documents=%d chunks_indexed=%d duration_ms=%d",
        tenant.id, True, len(documents), total_chunks, duration_ms,
    )

    return {"ok": True, "documents": documents, "generated_at": documents[-1]["generated_at"]}


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
