from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from storage.db import get_pool as _get_pool


async def create_tables() -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                id UUID PRIMARY KEY,
                name TEXT NOT NULL,
                created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                suspended BOOLEAN NOT NULL DEFAULT FALSE,
                widget_api_key TEXT NOT NULL UNIQUE,
                questions_quota INTEGER NOT NULL DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tenant_settings (
                tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
                top_k INTEGER NOT NULL DEFAULT 8,
                score_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                curated_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.92,
                max_question_chars INTEGER NOT NULL DEFAULT 1500,
                chunk_size INTEGER NOT NULL DEFAULT 200,
                chunk_overlap INTEGER NOT NULL DEFAULT 60
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS curated_answers (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                created TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS guardrails (
                id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                seeds TEXT[] NOT NULL,
                response TEXT NOT NULL,
                threshold DOUBLE PRECISION NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created TIMESTAMPTZ NOT NULL,
                started TIMESTAMPTZ,
                completed TIMESTAMPTZ,
                error TEXT,
                progress JSONB
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS crawl_pages (
                id UUID PRIMARY KEY,
                job_id UUID NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
                tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                content TEXT NOT NULL,
                crawled_at TIMESTAMPTZ NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS question_log (
                request_id UUID PRIMARY KEY,
                tenant_id UUID NOT NULL,
                timestamp TIMESTAMPTZ NOT NULL,
                question TEXT NOT NULL,
                word_count INTEGER NOT NULL,
                source TEXT,
                answer TEXT,
                answer_tokens INTEGER,
                curated_match_type TEXT,
                matched_question TEXT,
                guardrail_name TEXT,
                chunks JSONB,
                prompt_tokens INTEGER,
                error TEXT,
                timing_curated_check_ms INTEGER,
                timing_embed_ms INTEGER,
                timing_vector_search_ms INTEGER,
                timing_llm_ms INTEGER,
                timing_total_ms INTEGER
            )
        """)


async def get_tenant(tenant_id: UUID) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, created, suspended FROM tenants WHERE id = $1",
        tenant_id,
    )
    return dict(row) if row else None


async def insert_tenant(tenant_id: UUID, name: str, widget_api_key: str) -> dict:
    pool = await _get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO tenants (id, name, widget_api_key)
        VALUES ($1, $2, $3)
        RETURNING id, name, created, suspended, widget_api_key
        """,
        tenant_id,
        name,
        widget_api_key,
    )
    return dict(row)


async def delete_tenant(tenant_id: UUID) -> bool:
    pool = await _get_pool()
    result = await pool.execute("DELETE FROM tenants WHERE id = $1", tenant_id)
    return result == "DELETE 1"


async def set_suspended(tenant_id: UUID, suspended: bool) -> bool:
    pool = await _get_pool()
    result = await pool.execute(
        "UPDATE tenants SET suspended = $1 WHERE id = $2",
        suspended,
        tenant_id,
    )
    return result == "UPDATE 1"


async def get_settings(tenant_id: UUID) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        """
        SELECT top_k, score_threshold, curated_threshold,
               max_question_chars, chunk_size, chunk_overlap
        FROM tenant_settings WHERE tenant_id = $1
        """,
        tenant_id,
    )
    return dict(row) if row else None


async def upsert_settings(tenant_id: UUID, settings: Any) -> dict:
    pool = await _get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO tenant_settings
            (tenant_id, top_k, score_threshold, curated_threshold,
             max_question_chars, chunk_size, chunk_overlap)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (tenant_id) DO UPDATE SET
            top_k = EXCLUDED.top_k,
            score_threshold = EXCLUDED.score_threshold,
            curated_threshold = EXCLUDED.curated_threshold,
            max_question_chars = EXCLUDED.max_question_chars,
            chunk_size = EXCLUDED.chunk_size,
            chunk_overlap = EXCLUDED.chunk_overlap
        RETURNING top_k, score_threshold, curated_threshold,
                  max_question_chars, chunk_size, chunk_overlap
        """,
        tenant_id,
        settings.top_k,
        settings.score_threshold,
        settings.curated_threshold,
        settings.max_question_chars,
        settings.chunk_size,
        settings.chunk_overlap,
    )
    return dict(row)


async def get_usage(tenant_id: UUID) -> Optional[dict]:
    pool = await _get_pool()
    tenant_row = await pool.fetchrow(
        "SELECT suspended, questions_quota FROM tenants WHERE id = $1",
        tenant_id,
    )
    if tenant_row is None:
        return None

    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=30)

    usage_row = await pool.fetchrow(
        """
        SELECT
            COUNT(*) AS questions_asked,
            COALESCE(SUM(COALESCE(answer_tokens, 0) + COALESCE(prompt_tokens, 0)), 0) AS tokens_used
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2
        """,
        tenant_id,
        period_start,
    )

    return {
        "period_start": period_start,
        "period_end": now,
        "questions_asked": int(usage_row["questions_asked"]) if usage_row else 0,
        "questions_quota": tenant_row["questions_quota"],
        "tokens_used": int(usage_row["tokens_used"]) if usage_row else 0,
        "suspended": tenant_row["suspended"],
    }


async def get_vendor_tenants_summary() -> list[dict]:
    pool = await _get_pool()
    rows = await pool.fetch("""
        WITH
        stats_7d AS (
            SELECT
                tenant_id,
                COUNT(*)                                              AS questions_7d,
                COUNT(*) FILTER (WHERE source = 'rag')               AS rag_7d,
                COUNT(*) FILTER (WHERE source = 'curated')           AS curated_7d,
                COUNT(*) FILTER (WHERE source = 'guardrail')         AS guardrail_7d,
                COUNT(*) FILTER (WHERE source = 'error')             AS error_7d,
                CAST(AVG(timing_total_ms) AS INTEGER)                AS avg_response_ms_7d,
                MAX(timestamp)                                        AS last_question_at
            FROM question_log
            WHERE timestamp >= NOW() - INTERVAL '7 days'
            GROUP BY tenant_id
        ),
        stats_30d AS (
            SELECT tenant_id, COUNT(*) AS questions_30d
            FROM question_log
            WHERE timestamp >= NOW() - INTERVAL '30 days'
            GROUP BY tenant_id
        ),
        last_indexed AS (
            SELECT tenant_id, MAX(completed) AS last_indexed_at
            FROM jobs
            WHERE job_type = 'index' AND status = 'completed'
            GROUP BY tenant_id
        )
        SELECT
            t.id                                 AS tenant_id,
            t.name,
            t.suspended,
            t.questions_quota,
            COALESCE(s7.questions_7d, 0)         AS questions_7d,
            COALESCE(s30.questions_30d, 0)       AS questions_30d,
            COALESCE(s7.rag_7d, 0)               AS rag_7d,
            COALESCE(s7.curated_7d, 0)           AS curated_7d,
            COALESCE(s7.guardrail_7d, 0)         AS guardrail_7d,
            COALESCE(s7.error_7d, 0)             AS error_7d,
            s7.avg_response_ms_7d,
            s7.last_question_at,
            li.last_indexed_at
        FROM tenants t
        LEFT JOIN stats_7d  s7  ON t.id = s7.tenant_id
        LEFT JOIN stats_30d s30 ON t.id = s30.tenant_id
        LEFT JOIN last_indexed li ON t.id = li.tenant_id
    """)
    return [dict(r) for r in rows]


# ── Stubs implemented by other agents ───────────────────────────────────────

async def list_guardrails(tenant_id: UUID) -> list[dict]:
    pool = await _get_pool()
    rows = await pool.fetch(
        """
        SELECT id, name, seeds, response, threshold, enabled, created
        FROM guardrails
        WHERE tenant_id = $1
        ORDER BY created
        """,
        tenant_id,
    )
    return [dict(r) for r in rows]


async def get_guardrail(tenant_id: UUID, guardrail_id: UUID) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, name, seeds, response, threshold, enabled, created
        FROM guardrails
        WHERE id = $1 AND tenant_id = $2
        """,
        guardrail_id,
        tenant_id,
    )
    return dict(row) if row else None


async def insert_guardrail(
    tenant_id: UUID,
    guardrail_id: UUID,
    name: str,
    seeds: list[str],
    response: str,
    threshold: float,
    created: datetime,
) -> dict:
    pool = await _get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO guardrails (id, tenant_id, name, seeds, response, threshold, created)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id, name, seeds, response, threshold, enabled, created
        """,
        guardrail_id,
        tenant_id,
        name,
        seeds,
        response,
        threshold,
        created,
    )
    return dict(row)


async def update_guardrail(
    tenant_id: UUID, guardrail_id: UUID, fields: dict
) -> Optional[dict]:
    if not fields:
        return await get_guardrail(tenant_id, guardrail_id)

    allowed = {"name", "seeds", "response", "threshold", "enabled"}
    set_parts: list[str] = []
    values: list[Any] = [guardrail_id, tenant_id]
    idx = 3
    for key, value in fields.items():
        if key in allowed:
            set_parts.append(f"{key} = ${idx}")
            values.append(value)
            idx += 1

    if not set_parts:
        return await get_guardrail(tenant_id, guardrail_id)

    sql = f"""
        UPDATE guardrails
        SET {', '.join(set_parts)}
        WHERE id = $1 AND tenant_id = $2
        RETURNING id, name, seeds, response, threshold, enabled, created
    """
    pool = await _get_pool()
    row = await pool.fetchrow(sql, *values)
    return dict(row) if row else None


async def delete_guardrail(tenant_id: UUID, guardrail_id: UUID) -> bool:
    pool = await _get_pool()
    result = await pool.execute(
        "DELETE FROM guardrails WHERE id = $1 AND tenant_id = $2",
        guardrail_id,
        tenant_id,
    )
    return result == "DELETE 1"


async def list_curated_answers(tenant_id: UUID) -> list[dict]:
    pool = await _get_pool()
    rows = await pool.fetch(
        """
        SELECT id, question, answer, created
        FROM curated_answers
        WHERE tenant_id = $1
        ORDER BY created
        """,
        tenant_id,
    )
    return [dict(r) for r in rows]


async def get_curated_answer(tenant_id: UUID, curated_id: UUID) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, question, answer, created
        FROM curated_answers
        WHERE id = $1 AND tenant_id = $2
        """,
        curated_id,
        tenant_id,
    )
    return dict(row) if row else None


async def insert_curated_answer(
    tenant_id: UUID,
    curated_id: UUID,
    question: str,
    answer: str,
    created: datetime,
) -> dict:
    pool = await _get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO curated_answers (id, tenant_id, question, answer, created)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, question, answer, created
        """,
        curated_id,
        tenant_id,
        question,
        answer,
        created,
    )
    return dict(row)


async def update_curated_answer(
    tenant_id: UUID, curated_id: UUID, fields: dict
) -> Optional[dict]:
    if not fields:
        return await get_curated_answer(tenant_id, curated_id)

    allowed = {"question", "answer"}
    set_parts: list[str] = []
    values: list[Any] = [curated_id, tenant_id]
    idx = 3
    for key, value in fields.items():
        if key in allowed:
            set_parts.append(f"{key} = ${idx}")
            values.append(value)
            idx += 1

    if not set_parts:
        return await get_curated_answer(tenant_id, curated_id)

    sql = f"""
        UPDATE curated_answers
        SET {', '.join(set_parts)}
        WHERE id = $1 AND tenant_id = $2
        RETURNING id, question, answer, created
    """
    pool = await _get_pool()
    row = await pool.fetchrow(sql, *values)
    return dict(row) if row else None


async def delete_curated_answer(tenant_id: UUID, curated_id: UUID) -> bool:
    pool = await _get_pool()
    result = await pool.execute(
        "DELETE FROM curated_answers WHERE id = $1 AND tenant_id = $2",
        curated_id,
        tenant_id,
    )
    return result == "DELETE 1"


async def insert_question_log_entry(tenant_id: UUID, entry: Any) -> None:
    pool = await _get_pool()
    timing = entry.timing
    chunks_json = json.dumps([c.dict() for c in entry.chunks]) if entry.chunks else None
    await pool.execute(
        """
        INSERT INTO question_log (
            request_id, tenant_id, timestamp, question, word_count,
            source, answer, answer_tokens, curated_match_type, matched_question,
            guardrail_name, chunks, prompt_tokens, error,
            timing_curated_check_ms, timing_embed_ms, timing_vector_search_ms,
            timing_llm_ms, timing_total_ms
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12::jsonb, $13, $14, $15, $16, $17, $18, $19
        )
        ON CONFLICT (request_id) DO NOTHING
        """,
        entry.request_id,
        tenant_id,
        entry.timestamp,
        entry.question,
        entry.word_count,
        entry.source,
        entry.answer,
        entry.answer_tokens,
        entry.curated_match_type,
        entry.matched_question,
        entry.guardrail_name,
        chunks_json,
        entry.prompt_tokens,
        entry.error,
        timing.curated_check_ms if timing else None,
        timing.embed_ms if timing else None,
        timing.vector_search_ms if timing else None,
        timing.llm_ms if timing else None,
        timing.total_ms if timing else None,
    )


async def query_question_log(
    tenant_id: UUID,
    from_dt: Optional[datetime],
    to_dt: Optional[datetime],
    source: Optional[str],
    limit: int,
    offset: int,
) -> dict:
    """
    Return matching question log entries for a tenant with pagination.
    Result: {"items": [dict, ...], "total": int}

    Expected table schema (written by ask agent):
        request_id UUID PRIMARY KEY
        tenant_id UUID NOT NULL
        timestamp TIMESTAMPTZ NOT NULL
        question TEXT NOT NULL
        word_count INTEGER NOT NULL
        source TEXT
        answer TEXT
        answer_tokens INTEGER
        curated_match_type TEXT
        matched_question TEXT
        guardrail_name TEXT
        chunks JSONB
        prompt_tokens INTEGER
        error TEXT
        timing_curated_check_ms INTEGER
        timing_embed_ms INTEGER
        timing_vector_search_ms INTEGER
        timing_llm_ms INTEGER
        timing_total_ms INTEGER
    """
    pool = await _get_pool()

    conditions = ["tenant_id = $1"]
    values: list = [tenant_id]
    idx = 2

    if from_dt is not None:
        conditions.append(f"timestamp >= ${idx}")
        values.append(from_dt)
        idx += 1
    if to_dt is not None:
        conditions.append(f"timestamp <= ${idx}")
        values.append(to_dt)
        idx += 1
    if source is not None:
        conditions.append(f"source = ${idx}")
        values.append(source)
        idx += 1

    where = " AND ".join(conditions)

    count_row = await pool.fetchrow(
        f"SELECT COUNT(*) AS total FROM question_log WHERE {where}",
        *values,
    )
    total = int(count_row["total"])

    rows = await pool.fetch(
        f"""
        SELECT
            request_id, timestamp, question, word_count, source, answer,
            answer_tokens, curated_match_type, matched_question, guardrail_name,
            chunks, prompt_tokens, error,
            timing_curated_check_ms, timing_embed_ms,
            timing_vector_search_ms, timing_llm_ms, timing_total_ms
        FROM question_log
        WHERE {where}
        ORDER BY timestamp DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *values,
        limit,
        offset,
    )

    items = []
    for row in rows:
        r = dict(row)
        # Assemble timing sub-object only when at least one value is present
        has_timing = any(
            r.get(col) is not None
            for col in (
                "timing_curated_check_ms",
                "timing_embed_ms",
                "timing_vector_search_ms",
                "timing_llm_ms",
                "timing_total_ms",
            )
        )
        r["timing"] = (
            {
                "curated_check_ms": r.pop("timing_curated_check_ms"),
                "embed_ms": r.pop("timing_embed_ms"),
                "vector_search_ms": r.pop("timing_vector_search_ms"),
                "llm_ms": r.pop("timing_llm_ms"),
                "total_ms": r.pop("timing_total_ms"),
            }
            if has_timing
            else None
        )
        if not has_timing:
            for col in (
                "timing_curated_check_ms",
                "timing_embed_ms",
                "timing_vector_search_ms",
                "timing_llm_ms",
                "timing_total_ms",
            ):
                r.pop(col, None)
        r["chunks"] = r["chunks"] or []
        items.append(r)

    return {"items": items, "total": total}


async def validate_widget_key(widget_key: str) -> Optional[UUID]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT id FROM tenants WHERE widget_api_key = $1",
        widget_key,
    )
    return row["id"] if row else None
