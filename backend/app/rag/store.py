"""
Qdrant vector store — one collection per tenant (`aegis_{tenant_id}`), hard
isolation: no shared `tenant_id` filter that could leak on a bug, cleanly
removing a tenant = dropping its collection. See docs/rag.md.
"""
from __future__ import annotations

import os
import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

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
        if not await self._client.collection_exists(name):
            await self._client.create_collection(
                name, vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
            )

    async def upsert_chunks(
        self, tenant_id: str, source_path: str, chunks: list[dict], vectors: list[list[float]]
    ) -> int:
        """`chunks[i]` must contain at least {"text", "heading_path", "chunk_index"}."""
        if not chunks:
            return 0
        await self.ensure_collection(tenant_id, vector_size=len(vectors[0]))
        points = [
            PointStruct(
                id=_point_id(tenant_id, source_path, c["chunk_index"]),
                vector=vec,
                payload={"source_path": source_path, **c},
            )
            for c, vec in zip(chunks, vectors)
        ]
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

    async def search(self, tenant_id: str, query_vector: list[float], top_k: int = 5) -> list[dict]:
        name = collection_name(tenant_id)
        if not await self._client.collection_exists(name):
            return []
        result = await self._client.query_points(name, query=query_vector, limit=top_k)
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
            return {"ready": False, "points_count": 0}
        info = await self._client.get_collection(name)
        return {"ready": True, "points_count": info.points_count}

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
