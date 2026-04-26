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
        await conn.execute(
            "ALTER TABLE question_log ADD COLUMN IF NOT EXISTS timing_guardrail_check_ms INTEGER"
        )
        await conn.execute(
            "ALTER TABLE question_log ADD COLUMN IF NOT EXISTS embed_tokens INTEGER"
        )
        await conn.execute(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS url TEXT"
        )
        await conn.execute(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS name TEXT"
        )
        await conn.execute(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT FALSE"
        )
        await conn.execute(
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS params JSONB"
        )
        await conn.execute(
            "ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS demo_questions TEXT[] DEFAULT '{}'"
        )
        await conn.execute(
            "ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS system_prompt TEXT DEFAULT NULL"
        )
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS worker_heartbeat (
                worker_id  VARCHAR(64) PRIMARY KEY,
                started_at TIMESTAMPTZ NOT NULL,
                last_seen  TIMESTAMPTZ NOT NULL
            )
        """)


async def get_demo_questions(tenant_id: UUID) -> list[str]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT demo_questions FROM tenant_settings WHERE tenant_id = $1",
        tenant_id,
    )
    if not row:
        return []
    return list(row["demo_questions"] or [])


async def set_demo_questions(tenant_id: UUID, questions: list[str]) -> None:
    pool = await _get_pool()
    await pool.execute(
        "UPDATE tenant_settings SET demo_questions = $1 WHERE tenant_id = $2",
        questions,
        tenant_id,
    )


async def get_tenant(tenant_id: UUID) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, created, suspended FROM tenants WHERE id = $1",
        tenant_id,
    )
    return dict(row) if row else None


async def get_crawl_jobs(tenant_id: UUID) -> list[dict]:
    pool = await _get_pool()
    # Fetch crawl jobs
    crawl_rows = await pool.fetch(
        """
        SELECT job_id, status, created, started, completed, error, progress, url, name
        FROM jobs
        WHERE tenant_id = $1 AND job_type = 'crawl'
        ORDER BY created DESC
        """,
        tenant_id,
    )
    if not crawl_rows:
        return []

    # Fetch latest index job per crawl job (url stores crawl_job_id as string)
    index_rows = await pool.fetch(
        """
        SELECT DISTINCT ON (url) url, job_id AS index_job_id, status AS index_status,
               completed AS index_completed, progress AS index_progress
        FROM jobs
        WHERE tenant_id = $1
          AND job_type = 'index'
          AND url IS NOT NULL
        ORDER BY url, created DESC
        """,
        tenant_id,
    )
    # Build lookup: crawl_job_id_str -> index info
    index_by_crawl: dict[str, dict] = {}
    for ir in index_rows:
        p = ir["index_progress"]
        if p is not None and isinstance(p, str):
            p = json.loads(p)
        index_by_crawl[ir["url"]] = {
            "index_job_id": ir["index_job_id"],
            "index_status": ir["index_status"],
            "index_completed": ir["index_completed"],
            "embed_tokens": p.get("embed_tokens") if p else None,
            "pages_indexed": p.get("pages_indexed") if p else None,
        }

    result = []
    for row in crawl_rows:
        d = dict(row)
        crawl_id_str = str(d["job_id"])
        idx = index_by_crawl.get(crawl_id_str, {})
        d["embed_tokens"] = idx.get("embed_tokens")
        d["pages_indexed"] = idx.get("pages_indexed")
        d["index_job_id"] = idx.get("index_job_id")
        d["index_status"] = idx.get("index_status")
        d["index_completed"] = idx.get("index_completed")
        d["name"] = d.get("name")
        result.append(d)
    return result


async def delete_crawl_job(tenant_id: UUID, crawl_job_id: UUID) -> None:
    """Delete a crawl job and its associated index jobs. crawl_pages cascade-delete with the job."""
    pool = await _get_pool()
    crawl_id_str = str(crawl_job_id)
    async with pool.acquire() as conn:
        # Delete index jobs that reference this crawl
        await conn.execute(
            "DELETE FROM jobs WHERE tenant_id = $1 AND job_type = 'index' AND url = $2",
            tenant_id,
            crawl_id_str,
        )
        # Delete the crawl job itself (crawl_pages cascade via FK)
        await conn.execute(
            "DELETE FROM jobs WHERE tenant_id = $1 AND job_id = $2 AND job_type = 'crawl'",
            tenant_id,
            crawl_job_id,
        )


async def count_crawl_pages(crawl_job_id: UUID, tenant_id: UUID) -> int:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT COUNT(*) AS cnt FROM crawl_pages WHERE job_id = $1 AND tenant_id = $2",
        crawl_job_id,
        tenant_id,
    )
    return int(row["cnt"])


async def count_active_crawl_jobs(tenant_id: UUID) -> int:
    pool = await _get_pool()
    row = await pool.fetchrow(
        """
        SELECT COUNT(*) AS cnt
        FROM jobs
        WHERE tenant_id = $1 AND job_type = 'crawl' AND status != 'failed'
        """,
        tenant_id,
    )
    return int(row["cnt"])


async def get_widget_key(tenant_id: UUID) -> Optional[str]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT widget_api_key FROM tenants WHERE id = $1",
        tenant_id,
    )
    return row["widget_api_key"] if row else None


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
    # question_log has no FK constraint so must be cleaned up explicitly
    await pool.execute("DELETE FROM question_log WHERE tenant_id = $1", tenant_id)
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
               max_question_chars, chunk_size, chunk_overlap, system_prompt
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


async def get_system_prompt(tenant_id: UUID) -> Optional[str]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT system_prompt FROM tenant_settings WHERE tenant_id = $1",
        tenant_id,
    )
    return row["system_prompt"] if row else None


async def upsert_system_prompt(tenant_id: UUID, prompt: Optional[str]) -> None:
    pool = await _get_pool()
    await pool.execute(
        """
        INSERT INTO tenant_settings (tenant_id, system_prompt)
        VALUES ($1, $2)
        ON CONFLICT (tenant_id) DO UPDATE SET system_prompt = EXCLUDED.system_prompt
        """,
        tenant_id,
        prompt,
    )


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


async def upsert_worker_heartbeat(worker_id: str, started_at: datetime) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO worker_heartbeat (worker_id, started_at, last_seen)
            VALUES ($1, $2, NOW())
            ON CONFLICT (worker_id) DO UPDATE
                SET started_at = EXCLUDED.started_at,
                    last_seen  = NOW()
        """, worker_id, started_at)


async def touch_worker_heartbeat(worker_id: str) -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE worker_heartbeat SET last_seen = NOW() WHERE worker_id = $1",
            worker_id,
        )


async def get_system_health_stats() -> dict:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        tenants_row = await conn.fetchrow("""
            SELECT
                COUNT(*)                                  AS total,
                COUNT(*) FILTER (WHERE NOT suspended)     AS active,
                COUNT(*) FILTER (WHERE suspended)         AS suspended
            FROM tenants
        """)
        ql_row = await conn.fetchrow("""
            SELECT
                COUNT(*) FILTER (WHERE timestamp >= CURRENT_DATE)  AS questions_today,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE source = 'error' AND timestamp >= NOW() - INTERVAL '24 hours')
                    / NULLIF(COUNT(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '24 hours'), 0),
                    1
                )                                                   AS error_rate_24h,
                CAST(AVG(timing_total_ms) FILTER (
                    WHERE timestamp >= NOW() - INTERVAL '24 hours'
                ) AS INTEGER)                                       AS avg_response_ms_24h
            FROM question_log
        """)
        job_rows = await conn.fetch("""
            SELECT job_type, status, COUNT(*) AS cnt
            FROM jobs
            WHERE status IN ('pending', 'running')
            GROUP BY job_type, status
        """)
        oldest_rows = await conn.fetch("""
            SELECT job_type, EXTRACT(EPOCH FROM (NOW() - MIN(created)))::int AS oldest_pending_secs
            FROM jobs
            WHERE status = 'pending'
            GROUP BY job_type
        """)
        failed_row = await conn.fetchrow("""
            SELECT COUNT(*) AS failed_last_hour
            FROM jobs
            WHERE status = 'failed' AND completed >= NOW() - INTERVAL '1 hour'
        """)
        heartbeat_row = await conn.fetchrow(
            "SELECT started_at, last_seen FROM worker_heartbeat WHERE worker_id = 'default'"
        )

    jobs: dict = {}
    for r in job_rows:
        jt = r["job_type"]
        if jt not in jobs:
            jobs[jt] = {"pending": 0, "running": 0}
        jobs[jt][r["status"]] = r["cnt"]

    oldest: dict = {r["job_type"]: r["oldest_pending_secs"] for r in oldest_rows}

    worker_hb: dict = {}
    if heartbeat_row:
        worker_hb = {
            "started_at": heartbeat_row["started_at"].isoformat() if heartbeat_row["started_at"] else None,
            "last_seen":  heartbeat_row["last_seen"].isoformat()  if heartbeat_row["last_seen"]  else None,
        }

    return {
        "tenants": {"total": tenants_row["total"], "active": tenants_row["active"], "suspended": tenants_row["suspended"]},
        "questions_today": ql_row["questions_today"] or 0,
        "error_rate_24h": float(ql_row["error_rate_24h"] or 0),
        "avg_response_ms_24h": ql_row["avg_response_ms_24h"],
        "jobs": jobs,
        "oldest_pending_secs": oldest,
        "failed_last_hour": failed_row["failed_last_hour"],
        "worker": worker_hb,
    }


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
            timing_llm_ms, timing_total_ms,
            timing_guardrail_check_ms, embed_tokens
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12::jsonb, $13, $14, $15, $16, $17, $18, $19,
            $20, $21
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
        timing.guardrail_check_ms if timing else None,
        entry.embed_tokens,
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
            chunks, prompt_tokens, embed_tokens, error,
            timing_curated_check_ms, timing_embed_ms,
            timing_vector_search_ms, timing_llm_ms, timing_total_ms,
            timing_guardrail_check_ms
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
        timing_cols = (
            "timing_curated_check_ms",
            "timing_embed_ms",
            "timing_vector_search_ms",
            "timing_llm_ms",
            "timing_total_ms",
            "timing_guardrail_check_ms",
        )
        has_timing = any(r.get(col) is not None for col in timing_cols)
        r["timing"] = (
            {
                "curated_check_ms": r.pop("timing_curated_check_ms"),
                "guardrail_check_ms": r.pop("timing_guardrail_check_ms"),
                "embed_ms": r.pop("timing_embed_ms"),
                "vector_search_ms": r.pop("timing_vector_search_ms"),
                "llm_ms": r.pop("timing_llm_ms"),
                "total_ms": r.pop("timing_total_ms"),
            }
            if has_timing
            else None
        )
        if not has_timing:
            for col in timing_cols:
                r.pop(col, None)
        r["chunks"] = json.loads(r["chunks"]) if r["chunks"] else []
        items.append(r)

    return {"items": items, "total": total}


async def validate_widget_key(widget_key: str) -> Optional[UUID]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT id FROM tenants WHERE widget_api_key = $1",
        widget_key,
    )
    return row["id"] if row else None
