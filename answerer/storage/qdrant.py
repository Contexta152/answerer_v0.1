from __future__ import annotations

import asyncio
import os
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

_VECTOR_SIZE = 768  # text-embedding-004 default output dimension
_DISTANCE = Distance.COSINE

_client: QdrantClient | None = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        path = os.environ.get("QDRANT_PATH", "./qdrant_data")
        _client = QdrantClient(path=path)
    return _client


def _collection_name(tenant_id: UUID) -> str:
    return f"tenant_{tenant_id}"


def _ensure_collection(tenant_id: UUID) -> None:
    client = _get_client()
    name = _collection_name(tenant_id)
    existing = {c.name for c in client.get_collections().collections}
    if name not in existing:
        client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=_VECTOR_SIZE, distance=_DISTANCE),
        )


async def upsert_vectors(tenant_id: UUID, vectors: list[dict]) -> None:
    """
    Upsert vectors into the tenant's Qdrant collection.

    Each element of `vectors` must have:
        id:      str  — UUID string used as point ID
        vector:  list[float]
        payload: dict — arbitrary metadata (source URL, text, etc.)
    """
    client = _get_client()
    await asyncio.to_thread(_ensure_collection, tenant_id)
    points = [
        PointStruct(id=v["id"], vector=v["vector"], payload=v["payload"])
        for v in vectors
    ]
    await asyncio.to_thread(
        client.upsert,
        collection_name=_collection_name(tenant_id),
        points=points,
    )


async def delete_vectors(tenant_id: UUID, ids: list[str]) -> None:
    """Delete points by string UUID from the tenant's collection."""
    from qdrant_client.models import PointIdsList

    client = _get_client()
    await asyncio.to_thread(
        client.delete,
        collection_name=_collection_name(tenant_id),
        points_selector=PointIdsList(points=ids),
    )


async def delete_guardrail_vectors(tenant_id: UUID, guardrail_id: UUID) -> None:
    """Delete all seed vectors belonging to a guardrail from the tenant's collection."""
    client = _get_client()
    f = Filter(
        must=[
            FieldCondition(key="type", match=MatchValue(value="guardrail")),
            FieldCondition(key="guardrail_id", match=MatchValue(value=str(guardrail_id))),
        ]
    )
    await asyncio.to_thread(
        client.delete,
        collection_name=_collection_name(tenant_id),
        points_selector=FilterSelector(filter=f),
    )


async def similarity_search(
    tenant_id: UUID,
    query_vector: list[float],
    top_k: int,
    score_threshold: float,
    payload_filter: dict | None = None,
    must_not_payload: list[dict] | None = None,
) -> list[dict]:
    """
    Search for similar vectors in the tenant's collection.

    payload_filter: optional dict of {field: value} for exact-match must conditions.
    must_not_payload: optional list of {field: value} dicts — each dict is one must_not condition.
    Returns list of {"id": str, "score": float, "payload": dict}.
    """
    client = _get_client()
    await asyncio.to_thread(_ensure_collection, tenant_id)

    must_conditions = (
        [FieldCondition(key=k, match=MatchValue(value=v)) for k, v in payload_filter.items()]
        if payload_filter
        else []
    )
    must_not_conditions = (
        [FieldCondition(key=k, match=MatchValue(value=v)) for d in must_not_payload for k, v in d.items()]
        if must_not_payload
        else []
    )

    qdrant_filter: Filter | None = None
    if must_conditions or must_not_conditions:
        qdrant_filter = Filter(
            must=must_conditions or None,
            must_not=must_not_conditions or None,
        )

    response = await asyncio.to_thread(
        client.query_points,
        collection_name=_collection_name(tenant_id),
        query=query_vector,
        query_filter=qdrant_filter,
        limit=top_k,
        score_threshold=score_threshold,
        with_payload=True,
    )
    return [
        {"id": str(hit.id), "score": hit.score, "payload": hit.payload or {}}
        for hit in response.points
    ]


async def drop_collection(tenant_id: UUID):
    raise NotImplementedError
