from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from storage.db import get_pool
from storage.jobs import claim_pending_job, update_job_status
from storage.postgres import create_tables
from services.crawl import _run_crawl
from services.index import run_index_job

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 5  # seconds


async def _reset_stale_running_jobs() -> None:
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE jobs SET status = 'pending', started = NULL WHERE status = 'running'"
    )
    n = int(result.split()[-1])
    if n:
        logger.info("Reset %d stale running job(s) to pending", n)


async def _dispatch(job: dict) -> None:
    job_id: UUID = job["job_id"]
    tenant_id: UUID = job["tenant_id"]
    job_type: str = job["job_type"]

    params: dict = {}
    if job.get("params"):
        p = job["params"]
        if isinstance(p, str):
            p = json.loads(p)
        params = p

    logger.info("Dispatching %s job %s for tenant %s", job_type, job_id, tenant_id)

    if job_type == "crawl":
        url = job["url"]
        max_pages = params.get("max_pages", 500)
        max_depth = params.get("max_depth", 3)
        crawl_delay = params.get("crawl_delay", 0.0)
        await _run_crawl(job_id, tenant_id, url, max_pages, crawl_delay, max_depth)

    elif job_type == "index":
        crawl_job_id = UUID(job["url"])
        await run_index_job(tenant_id, job_id, crawl_job_id)

    else:
        raise ValueError(f"Unknown job_type: {job_type!r}")


async def _health_server() -> None:
    port = int(os.environ.get("PORT", 8080))

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1024)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(_handle, "0.0.0.0", port)
    logger.info("Health server listening on port %d", port)
    async with server:
        await server.serve_forever()


async def _worker_loop() -> None:
    await create_tables()
    await _reset_stale_running_jobs()
    logger.info("Worker polling for jobs (interval=%ds)", _POLL_INTERVAL)
    while True:
        try:
            job = await claim_pending_job()
            if job is None:
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            try:
                await _dispatch(job)
            except Exception as exc:
                logger.exception("Job %s failed: %s", job["job_id"], exc)
                try:
                    await update_job_status(
                        job["job_id"],
                        "failed",
                        error=str(exc),
                        completed=datetime.now(timezone.utc),
                    )
                except Exception:
                    pass

        except Exception as exc:
            logger.exception("Worker loop error: %s", exc)
            await asyncio.sleep(_POLL_INTERVAL)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger.info("Worker starting up")
    await asyncio.gather(_health_server(), _worker_loop())


if __name__ == "__main__":
    asyncio.run(main())
