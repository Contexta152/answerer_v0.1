from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from models import Job, JobProgress
from storage.db import get_pool


def _row_to_job(row) -> Job:
    progress = None
    if row["progress"] is not None:
        p = row["progress"]
        if isinstance(p, str):
            p = json.loads(p)
        progress = JobProgress(
            pages_crawled=p.get("pages_crawled"),
            pages_indexed=p.get("pages_indexed"),
            pages_vectorized=p.get("pages_vectorized"),
            pages_total=p.get("pages_total"),
            chunks_created=p.get("chunks_created"),
            vectors_upserted=p.get("vectors_upserted"),
            embed_tokens=p.get("embed_tokens"),
            embed_batches=p.get("embed_batches"),
            pages_failed=p.get("pages_failed"),
            queue_size=p.get("queue_size"),
            pages_store_failed=p.get("pages_store_failed"),
            pages_skipped_robots=p.get("pages_skipped_robots"),
            pages_skipped_scope=p.get("pages_skipped_scope"),
            pages_skipped_http=p.get("pages_skipped_http"),
            pages_skipped_content=p.get("pages_skipped_content"),
            stop_reason=p.get("stop_reason"),
        )
    return Job(
        job_id=row["job_id"],
        status=row["status"],
        created=row["created"],
        started=row["started"],
        completed=row["completed"],
        error=row["error"],
        progress=progress,
        url=row["url"] if "url" in row.keys() else None,
        name=row["name"] if "name" in row.keys() else None,
    )


async def create_job(tenant_id: UUID, job_type: str, url: str | None = None, name: str | None = None, params: dict | None = None) -> Job:
    """Insert a new job record with status 'pending' and return it."""
    pool = await get_pool()
    job_id = uuid4()
    now = datetime.now(timezone.utc)
    params_json = json.dumps(params) if params is not None else None
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO jobs (job_id, tenant_id, job_type, status, created, url, name, params)
            VALUES ($1, $2, $3, 'pending', $4, $5, $6, $7)
            RETURNING job_id, status, created, started, completed, error, progress, url, name
            """,
            job_id,
            tenant_id,
            job_type,
            now,
            url,
            name,
            params_json,
        )
    return _row_to_job(row)


async def get_job(tenant_id: UUID, job_id: UUID) -> Optional[Job]:
    """Return the job if it belongs to tenant_id, else None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT job_id, status, created, started, completed, error, progress, url, name
            FROM jobs
            WHERE job_id = $1 AND tenant_id = $2
            """,
            job_id,
            tenant_id,
        )
    if row is None:
        return None
    return _row_to_job(row)


# Allowed mutable fields for update_job_status
_MUTABLE_FIELDS = {"started", "completed", "error", "progress"}


async def update_job_status(job_id: UUID, status: str, **fields) -> None:
    """Update job status and any additional fields (started, completed, error, progress)."""
    pool = await get_pool()
    set_parts = ["status = $2"]
    values: list = [job_id, status]
    idx = 3

    # Reset cancel_requested when a job reaches a terminal state
    if status in ("completed", "failed"):
        set_parts.append("cancel_requested = FALSE")

    for key, value in fields.items():
        if key not in _MUTABLE_FIELDS:
            continue
        if key == "progress":
            set_parts.append(f"{key} = ${idx}::jsonb")
            values.append(json.dumps(value) if isinstance(value, dict) else value)
        else:
            set_parts.append(f"{key} = ${idx}")
            values.append(value)
        idx += 1

    sql = f"UPDATE jobs SET {', '.join(set_parts)} WHERE job_id = $1"
    async with pool.acquire() as conn:
        await conn.execute(sql, *values)


async def get_active_job(tenant_id: UUID, job_type: str) -> Optional[Job]:
    """Return a pending or running job of the given type for this tenant, or None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT job_id, status, created, started, completed, error, progress
            FROM jobs
            WHERE tenant_id = $1
              AND job_type = $2
              AND status IN ('pending', 'running')
            ORDER BY created DESC
            LIMIT 1
            """,
            tenant_id,
            job_type,
        )
    if row is None:
        return None
    return _row_to_job(row)


async def insert_crawl_page(job_id: UUID, tenant_id: UUID, url: str, content: str) -> None:
    """Store a raw crawled page for later indexing."""
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO crawl_pages (id, job_id, tenant_id, url, content, crawled_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            uuid4(),
            job_id,
            tenant_id,
            url,
            content,
            now,
        )


async def insert_crawl_http_error(
    job_id: UUID, tenant_id: UUID, url: str, status_code: Optional[int]
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO crawl_http_errors (id, job_id, tenant_id, url, status_code, failed_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            """,
            uuid4(), job_id, tenant_id, url, status_code,
        )


async def get_crawl_http_error_urls(job_id: UUID, tenant_id: UUID) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT url, status_code, failed_at FROM crawl_http_errors "
            "WHERE job_id = $1 AND tenant_id = $2 ORDER BY failed_at",
            job_id, tenant_id,
        )
    return [dict(r) for r in rows]


async def get_crawl_page_urls(job_id: UUID, tenant_id: UUID) -> list[dict]:
    """Return URLs and crawl times for a job — no content (can be large)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT url, crawled_at FROM crawl_pages WHERE job_id = $1 AND tenant_id = $2 ORDER BY crawled_at",
            job_id,
            tenant_id,
        )
    return [dict(row) for row in rows]


async def get_crawl_pages(job_id: UUID, tenant_id: UUID) -> list[dict]:
    """Return all pages stored for a crawl job, ordered by crawl time."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT url, content, crawled_at
            FROM crawl_pages
            WHERE job_id = $1 AND tenant_id = $2
            ORDER BY crawled_at
            """,
            job_id,
            tenant_id,
        )
    return [dict(row) for row in rows]


async def claim_pending_job(job_type: str) -> Optional[dict]:
    """Atomically claim the oldest pending job of the given type. Returns a dict or None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                SELECT job_id, tenant_id, job_type, url, name, params
                FROM jobs
                WHERE status = 'pending' AND job_type = $1
                ORDER BY created
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                job_type,
            )
            if row is None:
                return None
            await conn.execute(
                "UPDATE jobs SET status = 'running', started = $2 WHERE job_id = $1",
                row["job_id"],
                datetime.now(timezone.utc),
            )
            return dict(row)


async def request_cancel(job_id: UUID) -> None:
    """Set the cancel_requested flag in DB."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE jobs SET cancel_requested = TRUE WHERE job_id = $1",
            job_id,
        )


async def is_cancel_requested(job_id: UUID) -> bool:
    """Poll the cancel_requested flag from DB."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        val = await conn.fetchval(
            "SELECT cancel_requested FROM jobs WHERE job_id = $1",
            job_id,
        )
    return bool(val)


async def iter_crawl_pages(job_id: UUID, tenant_id: UUID, batch_size: int = 50):
    """Yield pages for a crawl job in batches, avoiding loading all into memory at once."""
    pool = await get_pool()
    offset = 0
    while True:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT url, content, crawled_at
                FROM crawl_pages
                WHERE job_id = $1 AND tenant_id = $2
                ORDER BY crawled_at
                LIMIT $3 OFFSET $4
                """,
                job_id,
                tenant_id,
                batch_size,
                offset,
            )
        if not rows:
            break
        for row in rows:
            yield dict(row)
        offset += batch_size
