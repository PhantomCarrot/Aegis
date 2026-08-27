"""
Qdrant vector store — one collection per tenant (`aegis_{tenant_id}`), hard
isolation: no shared `tenant_id` filter that could leak on a bug, cleanly
removing a tenant = dropping its collection. See docs/rag.md.
"""
from __future__ import annotations

import os
import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    Fusion,
    FusionQuery,
    MatchValue,
    PointStruct,
    Prefetch,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

# How many candidates each of dense/sparse contributes to RRF fusion before
# it narrows down to top_k — wider than top_k so fusion has real signal to
# work with. See docs/rag.md.
PREFETCH_MULTIPLIER = 4

DEFAULT_QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
# Optional — required by managed/remote instances that gate access behind a
# key (e.g. Qdrant Cloud). Absent for a local/self-hosted Qdrant with no
# auth in front of it (the docker-compose default).
DEFAULT_QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")


def collection_name(tenant_id: str) -> str:
    return f"aegis_{tenant_id}"


def _point_id(tenant_id: str, source_path: str, chunk_index: int) -> str:
    """Deterministic ID: re-indexing the same source cleanly overwrites its old chunks (upsert)."""
    key = f"{tenant_id}:{source_path}:{chunk_index}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


class QdrantStore:
    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        client: AsyncQdrantClient | None = None,
    ):
        self._client = client or AsyncQdrantClient(
            url=url or DEFAULT_QDRANT_URL,
            api_key=api_key if api_key is not None else DEFAULT_QDRANT_API_KEY,
        )

    async def ensure_collection(self, tenant_id: str, vector_size: int) -> None:
        name = collection_name(tenant_id)
        if await self._client.collection_exists(name):
            info = await self._client.get_collection(name)
            if isinstance(info.config.params.vectors, VectorParams):
                # Old schema: one anonymous dense vector, no sparse — RAG
                # data is 100% derived/regenerable, so silently drop and
                # recreate with the new named dense/sparse schema rather
                # than migrating in place. See docs/rag.md.
                await self._client.delete_collection(name)
            else:
                return
        await self._client.create_collection(
            name,
            vectors_config={"dense": VectorParams(size=vector_size, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams()},
        )

    async def upsert_chunks(
        self,
        tenant_id: str,
        source_path: str,
        chunks: list[dict],
        vectors: list[list[float]],
        sparse_vectors: list[SparseVector] | None = None,
    ) -> int:
        """`chunks[i]` must contain at least {"text", "heading_path", "chunk_index"}."""
        if not chunks:
            return 0
        await self.ensure_collection(tenant_id, vector_size=len(vectors[0]))
        points = []
        for i, (c, vec) in enumerate(zip(chunks, vectors)):
            point_vector: dict = {"dense": vec}
            if sparse_vectors:
                point_vector["sparse"] = sparse_vectors[i]
            points.append(
                PointStruct(
                    id=_point_id(tenant_id, source_path, c["chunk_index"]),
                    vector=point_vector,
                    payload={"source_path": source_path, **c},
                )
            )
        await self._client.upsert(collection_name(tenant_id), points=points)
        return len(points)

    async def delete_source(self, tenant_id: str, source_path: str) -> None:
        name = collection_name(tenant_id)
        if not await self._client.collection_exists(name):
            return
        await self._client.delete(
            name,
            points_selector=Filter(must=[FieldCondition(key="source_path", match=MatchValue(value=source_path))]),
        )

    async def search(
        self,
        tenant_id: str,
        query_vector: list[float],
        query_sparse: SparseVector | None = None,
        top_k: int = 5,
        score_threshold: float | None = None,
    ) -> list[dict]:
        """
        Hybrid search: dense (cosine) + sparse (BM25) candidates fused with
        Reciprocal Rank Fusion. Falls back to dense-only when `query_sparse`
        is omitted (e.g. a collection not yet migrated to the named-vector
        schema won't have a "sparse" field to query against). See
        docs/rag.md — the fused score is on the RRF scale, not cosine, so
        `score_threshold` must be tuned against it, not against raw
        similarity.
        """
        name = collection_name(tenant_id)
        if not await self._client.collection_exists(name):
            return []
        info = await self._client.get_collection(name)
        if isinstance(info.config.params.vectors, VectorParams):
            # Old schema (pre-hybrid-search, anonymous single vector) — no
            # "dense"/"sparse" fields to query against yet. Regenerating the
            # docs (POST /api/rag/generate) auto-migrates it via
            # ensure_collection; until then, there's nothing safe to search.
            return []

        if query_sparse is not None:
            result = await self._client.query_points(
                name,
                prefetch=[
                    Prefetch(query=query_vector, using="dense", limit=top_k * PREFETCH_MULTIPLIER),
                    Prefetch(query=query_sparse, using="sparse", limit=top_k * PREFETCH_MULTIPLIER),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=top_k,
                score_threshold=score_threshold,
            )
        else:
            result = await self._client.query_points(
                name, query=query_vector, using="dense", limit=top_k, score_threshold=score_threshold
            )
        return [{"score": p.score, **(p.payload or {})} for p in result.points]

    async def list_chunks(self, tenant_id: str) -> list[dict]:
        """
        All chunks indexed for this tenant (no vector search — just reading
        the content). Used to browse the RAG index from the UI (GET
        /api/rag/documents), not for search.
        """
        name = collection_name(tenant_id)
        if not await self._client.collection_exists(name):
            return []

        chunks: list[dict] = []
        offset = None
        while True:
            points, offset = await self._client.scroll(
                name, limit=200, offset=offset, with_payload=True, with_vectors=False
            )
            chunks.extend(p.payload for p in points if p.payload)
            if offset is None:
                break
        return chunks

    async def status(self, tenant_id: str) -> dict:
        name = collection_name(tenant_id)
        if not await self._client.collection_exists(name):
            return {"ready": False, "points_count": 0, "generated_at": None}
        info = await self._client.get_collection(name)
        generated_at = None
        if info.points_count:
            # One point is enough — index_text() stamps the same
            # generated_at on every chunk of a given generate() call (see
            # app/rag/indexer.py). No dedicated marker point/collection.
            points, _ = await self._client.scroll(
                name, limit=1, with_payload=["generated_at"], with_vectors=False
            )
            if points and points[0].payload:
                generated_at = points[0].payload.get("generated_at")
        return {"ready": True, "points_count": info.points_count, "generated_at": generated_at}

    async def close(self) -> None:
        await self._client.close()


_store: QdrantStore | None = None


def get_store() -> QdrantStore:
    """A single Qdrant client for the whole process — no need for one per
    tenant, isolation happens at the collection level (see collection_name)."""
    global _store
    if _store is None:
        _store = QdrantStore()
    return _store


def reset_store() -> None:
    """Used by tests to start each case with a clean store."""
    global _store
    _store = None
