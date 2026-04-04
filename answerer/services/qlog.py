from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from models import Chunk, QuestionLogEntry, Timing
from storage import postgres


async def query_question_log(
    tenant_id: UUID,
    from_dt: Optional[datetime],
    to_dt: Optional[datetime],
    source: Optional[str],
    limit: int,
    offset: int,
) -> dict:
    """
    Return paginated question log entries for a tenant.
    Result: {"items": list[QuestionLogEntry], "total": int}
    """
    result = await postgres.query_question_log(
        tenant_id=tenant_id,
        from_dt=from_dt,
        to_dt=to_dt,
        source=source,
        limit=limit,
        offset=offset,
    )

    items = [_row_to_entry(row) for row in result["items"]]
    return {"items": items, "total": result["total"]}


def _row_to_entry(row: dict) -> QuestionLogEntry:
    timing: Optional[Timing] = None
    if row.get("timing") is not None:
        t = row["timing"]
        timing = Timing(
            curated_check_ms=t.get("curated_check_ms"),
            embed_ms=t.get("embed_ms"),
            vector_search_ms=t.get("vector_search_ms"),
            llm_ms=t.get("llm_ms"),
            total_ms=t.get("total_ms"),
        )

    chunks = [
        Chunk(
            source=c["source"],
            score=c["score"],
            tokens=c["tokens"],
            text=c["text"],
        )
        for c in (row.get("chunks") or [])
    ]

    return QuestionLogEntry(
        request_id=row["request_id"],
        timestamp=row["timestamp"],
        question=row["question"],
        word_count=row["word_count"],
        source=row.get("source"),
        answer=row.get("answer"),
        answer_tokens=row.get("answer_tokens"),
        curated_match_type=row.get("curated_match_type"),
        matched_question=row.get("matched_question"),
        guardrail_name=row.get("guardrail_name"),
        chunks=chunks,
        prompt_tokens=row.get("prompt_tokens"),
        error=row.get("error"),
        timing=timing,
    )
