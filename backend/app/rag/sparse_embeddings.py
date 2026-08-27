"""
Sparse (BM25-style) keyword embeddings via fastembed — local ONNX runtime,
no torch/API dependency (see backend/pyproject.toml). Paired with the dense
embeddings in app/rag/embeddings.py for hybrid search (RRF fusion in
app/rag/store.py). See docs/rag.md.

Dense embeddings alone miss exact keyword/identifier matches (a namespace
name, a resource kind) that don't carry much semantic weight but matter a
lot for infra docs — sparse search catches those.
"""
from __future__ import annotations

import os

from fastembed import SparseTextEmbedding
from qdrant_client.models import SparseVector

DEFAULT_SPARSE_MODEL = os.getenv("AEGIS_SPARSE_EMBED_MODEL", "Qdrant/bm25")

_model: SparseTextEmbedding | None = None


def _get_model() -> SparseTextEmbedding:
    # Loading a fastembed model isn't free (ONNX weights, downloaded once
    # and cached on disk by fastembed itself) — a process-wide singleton,
    # same spirit as app/rag/store.py's get_store().
    global _model
    if _model is None:
        _model = SparseTextEmbedding(model_name=DEFAULT_SPARSE_MODEL)
    return _model


def reset_model() -> None:
    """Used by tests to force a fresh singleton."""
    global _model
    _model = None


def _to_sparse_vector(embedding) -> SparseVector:
    return SparseVector(indices=embedding.indices.tolist(), values=embedding.values.tolist())


def embed_texts_sparse(texts: list[str]) -> list[SparseVector]:
    """
    Returns one SparseVector per text, in the same order as `texts`.
    Synchronous and CPU-bound (ONNX) — call via `asyncio.to_thread` from
    async code, same as app/rag/indexer.py does.
    """
    if not texts:
        return []
    model = _get_model()
    return [_to_sparse_vector(e) for e in model.embed(texts)]


def embed_query_sparse(text: str) -> SparseVector:
    """
    Uses fastembed's `query_embed` (vs. `embed`) — BM25 weighs query and
    document terms differently, same reason app/rag/embeddings.py could one
    day need a query-specific dense model.
    """
    model = _get_model()
    return next(_to_sparse_vector(e) for e in model.query_embed([text]))
