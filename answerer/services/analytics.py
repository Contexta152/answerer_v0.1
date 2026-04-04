from __future__ import annotations

from datetime import datetime
from uuid import UUID

from storage.db import get_pool


async def get_analytics(tenant_id: UUID, from_dt: datetime, to_dt: datetime) -> dict:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT
            COUNT(*)                                              AS total,
            COUNT(*) FILTER (WHERE source = 'rag')               AS rag,
            COUNT(*) FILTER (WHERE source = 'curated')           AS curated,
            COUNT(*) FILTER (WHERE source = 'guardrail')         AS guardrail,
            COUNT(*) FILTER (WHERE source = 'error')             AS error,
            CAST(AVG(timing_total_ms) AS INTEGER)                AS avg_response_ms
        FROM question_log
        WHERE tenant_id = $1
          AND timestamp >= $2
          AND timestamp <= $3
        """,
        tenant_id,
        from_dt,
        to_dt,
    )
    return {
        "period_start": from_dt,
        "period_end": to_dt,
        "total_questions": int(row["total"]),
        "by_source": {
            "rag": int(row["rag"]),
            "curated": int(row["curated"]),
            "guardrail": int(row["guardrail"]),
            "error": int(row["error"]),
        },
        "avg_response_ms": row["avg_response_ms"],
    }
