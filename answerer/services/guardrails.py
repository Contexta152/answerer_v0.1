from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from models import Guardrail
from services.embed import embed_texts, _TASK_TYPE_DOCUMENT as RETRIEVAL_DOCUMENT
from storage import postgres, qdrant


def _row_to_guardrail(row: dict) -> Guardrail:
    return Guardrail(
        id=row["id"],
        name=row["name"],
        seeds=list(row["seeds"]),
        response=row["response"],
        threshold=row["threshold"],
        enabled=row["enabled"],
        created=row["created"],
    )


async def list_guardrails(tenant_id: UUID) -> list[Guardrail]:
    rows = await postgres.list_guardrails(tenant_id)
    return [_row_to_guardrail(r) for r in rows]


async def create_guardrail(
    tenant_id: UUID,
    name: str,
    seeds: list[str],
    response: str,
    threshold: float,
) -> Guardrail:
    guardrail_id = uuid4()
    created = datetime.now(timezone.utc)

    # Embed every seed phrase and upsert into Qdrant
    vectors = await embed_texts(seeds, task_type=RETRIEVAL_DOCUMENT)
    qdrant_points = [
        {
            "id": str(uuid4()),
            "vector": vec,
            "payload": {
                "type": "guardrail",
                "guardrail_id": str(guardrail_id),
                "tenant_id": str(tenant_id),
                "seed_text": seed,
                "name": name,
                "response": response,
                "threshold": threshold,
                "enabled": True,
            },
        }
        for seed, vec in zip(seeds, vectors)
    ]
    await qdrant.upsert_vectors(tenant_id, qdrant_points)

    row = await postgres.insert_guardrail(
        tenant_id, guardrail_id, name, seeds, response, threshold, created
    )
    return _row_to_guardrail(row)


async def update_guardrail(
    tenant_id: UUID,
    guardrail_id: UUID,
    **fields,
) -> Guardrail | None:
    # Apply Postgres update first so we have the authoritative post-update state
    updated_row = await postgres.update_guardrail(tenant_id, guardrail_id, fields)
    if updated_row is None:
        return None

    # Re-sync Qdrant: delete existing seed vectors, re-embed and re-upsert
    await qdrant.delete_guardrail_vectors(tenant_id, guardrail_id)

    current_seeds = list(updated_row["seeds"])
    if current_seeds:
        vectors = await embed_texts(current_seeds, task_type=RETRIEVAL_DOCUMENT)
        qdrant_points = [
            {
                "id": str(uuid4()),
                "vector": vec,
                "payload": {
                    "type": "guardrail",
                    "guardrail_id": str(guardrail_id),
                    "tenant_id": str(tenant_id),
                    "seed_text": seed,
                    "name": updated_row["name"],
                    "response": updated_row["response"],
                    "threshold": updated_row["threshold"],
                    "enabled": updated_row["enabled"],
                },
            }
            for seed, vec in zip(current_seeds, vectors)
        ]
        await qdrant.upsert_vectors(tenant_id, qdrant_points)

    return _row_to_guardrail(updated_row)


async def delete_guardrail(tenant_id: UUID, guardrail_id: UUID) -> bool:
    # Check existence before touching Qdrant
    row = await postgres.get_guardrail(tenant_id, guardrail_id)
    if row is None:
        return False

    await qdrant.delete_guardrail_vectors(tenant_id, guardrail_id)
    await postgres.delete_guardrail(tenant_id, guardrail_id)
    return True
