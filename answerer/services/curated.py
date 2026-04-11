from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException

import storage.postgres as pg
import storage.qdrant as qdrant_store
from models import CuratedAnswer
from services.embed import embed_text


def _row_to_model(row: dict) -> CuratedAnswer:
    return CuratedAnswer(
        id=row["id"],
        question=row["question"],
        answer=row["answer"],
        created=row["created"],
    )


async def list_curated_answers(tenant_id: UUID) -> list[CuratedAnswer]:
    rows = await pg.list_curated_answers(tenant_id)
    return [_row_to_model(r) for r in rows]


async def create_curated_answer(
    tenant_id: UUID, question: str, answer: str
) -> CuratedAnswer:
    curated_id = uuid4()
    created = datetime.now(timezone.utc)

    vector, _embed_tok = await embed_text(question, tenant_id)

    row = await pg.insert_curated_answer(
        tenant_id, curated_id, question, answer, created
    )

    await qdrant_store.upsert_vectors(
        tenant_id,
        [
            {
                "id": str(curated_id),
                "vector": vector,
                "payload": {
                    "type": "curated",
                    "curated_id": str(curated_id),
                    "question": question,
                    "answer": answer,
                },
            }
        ],
    )

    return _row_to_model(row)


async def update_curated_answer(
    tenant_id: UUID,
    curated_id: UUID,
    question: Optional[str],
    answer: Optional[str],
) -> CuratedAnswer:
    existing = await pg.get_curated_answer(tenant_id, curated_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Curated answer not found")

    fields: dict = {}
    if question is not None:
        fields["question"] = question
    if answer is not None:
        fields["answer"] = answer

    if fields:
        row = await pg.update_curated_answer(tenant_id, curated_id, fields)
    else:
        row = existing

    # Re-embed with current question (may be unchanged) to keep Qdrant payload in sync
    new_question = fields.get("question", existing["question"])
    new_answer = fields.get("answer", existing["answer"])
    vector, _embed_tok = await embed_text(new_question, tenant_id)

    await qdrant_store.upsert_vectors(
        tenant_id,
        [
            {
                "id": str(curated_id),
                "vector": vector,
                "payload": {
                    "type": "curated",
                    "curated_id": str(curated_id),
                    "question": new_question,
                    "answer": new_answer,
                },
            }
        ],
    )

    return _row_to_model(row)


async def delete_curated_answer(tenant_id: UUID, curated_id: UUID) -> None:
    existing = await pg.get_curated_answer(tenant_id, curated_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Curated answer not found")

    await pg.delete_curated_answer(tenant_id, curated_id)
    await qdrant_store.delete_vectors(tenant_id, [str(curated_id)])
