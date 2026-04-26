from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from uuid import UUID

import httpx
from fastapi import HTTPException

import storage.jobs as jobs_store
import storage.postgres as pg_store
from models import Job

_USER_AGENT = "AnswererBot/1.0"

logger = logging.getLogger(__name__)


class _LinkExtractor(HTMLParser):
    """Minimal HTML parser that collects href values from <a> tags."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


async def start_crawl(
    tenant_id: UUID,
    url: str,
    max_pages: int,
    name: str | None = None,
    crawl_delay: float = 0.0,
    max_depth: int = 3,
) -> Job:
    tenant = await pg_store.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    kb_count = await pg_store.count_active_crawl_jobs(tenant_id)
    if kb_count >= 5:
        raise HTTPException(
            status_code=409,
            detail="Maximum of 5 knowledge bases allowed. Delete one to add another.",
        )

    active = await jobs_store.get_active_job(tenant_id, "crawl")
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="A crawl job is already running for this tenant",
        )

    job = await jobs_store.create_job(
        tenant_id, "crawl", url=url, name=name,
        params={"max_pages": max_pages, "max_depth": max_depth, "crawl_delay": crawl_delay},
    )
    return job


async def get_crawl_status(tenant_id: UUID, job_id: UUID) -> Job:
    job = await jobs_store.get_job(tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def stop_crawl(tenant_id: UUID, job_id: UUID) -> None:
    job = await jobs_store.get_job(tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("pending", "running"):
        await jobs_store.request_cancel(job_id)


async def delete_crawl(tenant_id: UUID, job_id: UUID) -> None:
    """Stop if running, delete Qdrant vectors, then delete all job records."""
    import storage.qdrant as qdrant_store
    job = await jobs_store.get_job(tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("pending", "running"):
        await jobs_store.request_cancel(job_id)
    await qdrant_store.delete_vectors_by_crawl_job(tenant_id, job_id)
    await pg_store.delete_crawl_job(tenant_id, job_id)


async def _fetch_robots(robots_url: str):
    """Fetch and parse robots.txt; falls back to allow-all on timeout or error."""
    import urllib.robotparser

    def _read():
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
        except Exception:
            pass
        return rp

    try:
        return await asyncio.wait_for(asyncio.to_thread(_read), timeout=5.0)
    except Exception:
        return urllib.robotparser.RobotFileParser()  # unread parser allows everything


_CRAWL_CONCURRENCY    = 10   # parallel page fetches
_PROGRESS_EVERY       = 5    # write progress to DB every N pages stored
_CANCEL_CHECK_EVERY   = 10   # check cancel flag every N pages stored


async def _run_crawl(job_id: UUID, tenant_id: UUID, seed_url: str, max_pages: int, crawl_delay: float = 0.0, max_depth: int = 3) -> None:
    """Concurrent BFS crawl from seed_url — up to _CRAWL_CONCURRENCY parallel fetches."""
    from urllib.parse import urljoin, urlparse

    logger.info("Crawl %s starting: seed=%s max_pages=%d max_depth=%d concurrency=%d",
                job_id, seed_url, max_pages, max_depth, _CRAWL_CONCURRENCY)

    pages_crawled        = 0
    pages_store_failed   = 0
    pages_skipped_robots = 0
    pages_skipped_scope  = 0
    pages_skipped_http   = 0
    pages_skipped_content = 0
    cancelled            = False

    try:
        parsed_seed      = urlparse(seed_url)
        base_netloc      = parsed_seed.netloc
        base_scheme      = parsed_seed.scheme
        seed_path_prefix = parsed_seed.path.rstrip("/") or "/"

        def _canonical(url: str) -> str:
            p = urlparse(url)
            return p._replace(query="", fragment="").geturl()

        def _in_scope(url: str) -> bool:
            p = urlparse(url)
            if p.netloc != base_netloc:
                return False
            if seed_path_prefix != "/":
                pp = p.path
                if pp != seed_path_prefix and not pp.startswith(seed_path_prefix + "/"):
                    return False
            return True

        seed_canonical = _canonical(seed_url)
        rp = await _fetch_robots(f"{base_scheme}://{base_netloc}/robots.txt")

        visited: set[str] = set()
        queued:  set[str] = {seed_canonical}
        queue:   deque[tuple[str, int]] = deque([(seed_canonical, 0)])

        def _progress() -> dict:
            return {
                "pages_crawled":        pages_crawled,
                "pages_total":          None,
                "queue_size":           min(len(queue), max(0, max_pages - pages_crawled)),
                "pages_store_failed":   pages_store_failed,
                "pages_skipped_robots": pages_skipped_robots,
                "pages_skipped_scope":  pages_skipped_scope,
                "pages_skipped_http":   pages_skipped_http,
                "pages_skipped_content":pages_skipped_content,
            }

        async def _fetch_one(client: httpx.AsyncClient, url: str, depth: int):
            """Fetch a single page and return (new_links, stored_body | None)."""
            nonlocal pages_skipped_robots, pages_skipped_scope, pages_skipped_http, pages_skipped_content
            if not _in_scope(url):
                pages_skipped_scope += 1
                return [], None
            if not rp.can_fetch(_USER_AGENT, url):
                pages_skipped_robots += 1
                return [], None
            try:
                resp = await client.get(url)
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                logger.debug("Crawl %s: request error %s: %s", job_id, url, e)
                pages_skipped_http += 1
                return [], None
            if resp.status_code != 200:
                pages_skipped_http += 1
                return [], None
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                pages_skipped_content += 1
                return [], None
            body = resp.text
            if crawl_delay > 0:
                await asyncio.sleep(crawl_delay)
            new_links: list[tuple[str, int]] = []
            if "text/html" in content_type and depth < max_depth:
                extractor = _LinkExtractor()
                extractor.feed(body)
                for href in extractor.links:
                    abs_url = _canonical(urljoin(url, href))
                    p = urlparse(abs_url)
                    if p.scheme in ("http", "https") and _in_scope(abs_url):
                        new_links.append((abs_url, depth + 1))
            return new_links, body

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            pending: set[asyncio.Task] = set()

            while (queue or pending) and pages_crawled < max_pages and not cancelled:
                # Fill up to concurrency limit from the queue
                while queue and pages_crawled + len(pending) < max_pages:
                    url, depth = queue.popleft()
                    if url in visited:
                        continue
                    visited.add(url)
                    task = asyncio.create_task(_fetch_one(client, url, depth))
                    task.url   = url    # type: ignore[attr-defined]
                    task.depth = depth  # type: ignore[attr-defined]
                    pending.add(task)
                    if len(pending) >= _CRAWL_CONCURRENCY:
                        break

                if not pending:
                    break

                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)

                for task in done:
                    new_links, body = task.result()
                    url   = task.url    # type: ignore[attr-defined]
                    depth = task.depth  # type: ignore[attr-defined]

                    if body is not None:
                        try:
                            await jobs_store.insert_crawl_page(job_id, tenant_id, url, body)
                            pages_crawled += 1
                            logger.debug("Crawl %s: stored %d/%d: %s", job_id, pages_crawled, max_pages, url)
                            if pages_crawled % _PROGRESS_EVERY == 0:
                                await jobs_store.update_job_status(job_id, "running", progress=_progress())
                            if pages_crawled % _CANCEL_CHECK_EVERY == 0:
                                if await jobs_store.is_cancel_requested(job_id):
                                    cancelled = True
                                    for t in pending:
                                        t.cancel()
                                    break
                        except Exception as store_exc:
                            logger.warning("Crawl %s: store failed %s: %s", job_id, url, store_exc)
                            pages_store_failed += 1

                    if cancelled:
                        break

                    # Gate on pages_crawled only (not + pending) so failed tasks
                    # don't prematurely close the queue and cause a short crawl.
                    for link_url, link_depth in new_links:
                        if link_url not in queued and pages_crawled < max_pages:
                            queued.add(link_url)
                            queue.append((link_url, link_depth))

        if cancelled:
            logger.info("Crawl %s stopped by user after %d pages", job_id, pages_crawled)
            await jobs_store.update_job_status(
                job_id, "failed", error="Stopped by user",
                completed=datetime.now(timezone.utc), progress=_progress(),
            )
            return

        stop_reason = "max_pages reached" if pages_crawled >= max_pages else "queue exhausted"
        logger.info(
            "Crawl %s completed: %s. crawled=%d store_failed=%d skipped_robots=%d "
            "skipped_scope=%d skipped_http=%d skipped_content=%d",
            job_id, stop_reason, pages_crawled, pages_store_failed,
            pages_skipped_robots, pages_skipped_scope, pages_skipped_http, pages_skipped_content,
        )
        final_progress = _progress()
        final_progress["pages_total"]  = pages_crawled
        final_progress["stop_reason"]  = stop_reason
        await jobs_store.update_job_status(
            job_id, "completed", completed=datetime.now(timezone.utc), progress=final_progress,
        )

    except Exception as exc:
        logger.exception("Crawl %s failed with unhandled exception after %d pages", job_id, pages_crawled)
        try:
            await jobs_store.update_job_status(
                job_id, "failed", error=str(exc), completed=datetime.now(timezone.utc),
            )
        except Exception:
            pass
