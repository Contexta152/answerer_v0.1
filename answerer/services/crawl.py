from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from uuid import UUID

import httpx
from fastapi import BackgroundTasks, HTTPException

import storage.jobs as jobs_store
import storage.postgres as pg_store
from models import Job

# Job IDs for which a stop has been requested. Checked between pages in _run_crawl.
_cancel_requested: set[UUID] = set()

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
    background_tasks: BackgroundTasks,
    name: str | None = None,
    crawl_delay: float = 0.0,
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

    job = await jobs_store.create_job(tenant_id, "crawl", url=url, name=name)
    background_tasks.add_task(_run_crawl, job.job_id, tenant_id, url, max_pages, crawl_delay)
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
        _cancel_requested.add(job_id)


async def delete_crawl(tenant_id: UUID, job_id: UUID) -> None:
    """Stop if running, delete Qdrant vectors, then delete all job records."""
    import storage.qdrant as qdrant_store
    job = await jobs_store.get_job(tenant_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("pending", "running"):
        _cancel_requested.add(job_id)
    await qdrant_store.delete_vectors_by_crawl_job(tenant_id, job_id)
    await pg_store.delete_crawl_job(tenant_id, job_id)


async def _fetch_robots(robots_url: str):
    """Fetch and parse robots.txt in a thread to avoid blocking the event loop."""
    import urllib.robotparser

    def _read():
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            rp.read()
        except Exception:
            pass
        return rp

    return await asyncio.to_thread(_read)


async def _run_crawl(job_id: UUID, tenant_id: UUID, seed_url: str, max_pages: int, crawl_delay: float = 0.0) -> None:
    """Background task: BFS crawl from seed_url, store pages, update job progress."""
    logger.info("Crawl %s starting: seed=%s max_pages=%d", job_id, seed_url, max_pages)
    pages_crawled = 0
    try:
        await jobs_store.update_job_status(
            job_id, "running", started=datetime.now(timezone.utc)
        )

        from urllib.parse import urljoin, urlparse

        parsed_seed = urlparse(seed_url)
        base_netloc = parsed_seed.netloc
        base_scheme = parsed_seed.scheme
        # Normalise seed path: /guide and /guide/ both give prefix /guide
        seed_path_prefix = parsed_seed.path.rstrip("/") or "/"

        rp = await _fetch_robots(f"{base_scheme}://{base_netloc}/robots.txt")

        visited: set[str] = set()
        queued: set[str] = {seed_url}  # tracks everything ever enqueued to prevent duplicates
        queue: deque[str] = deque([seed_url])
        pages_store_failed = 0
        pages_skipped_robots = 0
        pages_skipped_scope = 0
        pages_skipped_http = 0
        pages_skipped_content = 0

        def _progress() -> dict:
            return {
                "pages_crawled": pages_crawled,
                "pages_total": None,
                "queue_size": len(queue),
                "pages_store_failed": pages_store_failed,
                "pages_skipped_robots": pages_skipped_robots,
                "pages_skipped_scope": pages_skipped_scope,
                "pages_skipped_http": pages_skipped_http,
                "pages_skipped_content": pages_skipped_content,
            }

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            while queue and pages_crawled < max_pages:
                if job_id in _cancel_requested:
                    _cancel_requested.discard(job_id)
                    logger.info("Crawl %s stopped by user after %d pages", job_id, pages_crawled)
                    await jobs_store.update_job_status(
                        job_id,
                        "failed",
                        error="Stopped by user",
                        completed=datetime.now(timezone.utc),
                        progress=_progress(),
                    )
                    return

                current_url = queue.popleft()
                if current_url in visited:
                    continue
                visited.add(current_url)

                parsed = urlparse(current_url)
                if parsed.netloc != base_netloc:
                    pages_skipped_scope += 1
                    continue
                # Only crawl pages at or below the seed path
                if seed_path_prefix != "/":
                    p_path = parsed.path
                    if p_path != seed_path_prefix and not p_path.startswith(seed_path_prefix + "/"):
                        pages_skipped_scope += 1
                        continue
                if not rp.can_fetch(_USER_AGENT, current_url):
                    logger.debug("Crawl %s: robots.txt blocked %s", job_id, current_url)
                    pages_skipped_robots += 1
                    continue

                try:
                    resp = await client.get(current_url)
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    logger.debug("Crawl %s: request error for %s: %s", job_id, current_url, e)
                    pages_skipped_http += 1
                    continue

                if resp.status_code != 200:
                    logger.debug("Crawl %s: HTTP %d for %s", job_id, resp.status_code, current_url)
                    pages_skipped_http += 1
                    continue

                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    logger.debug("Crawl %s: skipping content-type=%s for %s", job_id, content_type, current_url)
                    pages_skipped_content += 1
                    continue

                body = resp.text
                try:
                    await jobs_store.insert_crawl_page(job_id, tenant_id, current_url, body)
                except Exception as store_exc:
                    logger.warning("Crawl %s: failed to store page %s: %s", job_id, current_url, store_exc)
                    pages_store_failed += 1
                    continue

                pages_crawled += 1
                logger.debug("Crawl %s: stored page %d/%d: %s", job_id, pages_crawled, max_pages, current_url)

                await jobs_store.update_job_status(
                    job_id,
                    "running",
                    progress=_progress(),
                )

                if crawl_delay > 0:
                    await asyncio.sleep(crawl_delay)

                if "text/html" in content_type:
                    extractor = _LinkExtractor()
                    extractor.feed(body)
                    new_links = 0
                    for href in extractor.links:
                        abs_url = urljoin(current_url, href).split("#")[0]
                        p = urlparse(abs_url)
                        if not (p.scheme in ("http", "https") and p.netloc == base_netloc):
                            continue
                        if seed_path_prefix != "/" and p.path != seed_path_prefix and not p.path.startswith(seed_path_prefix + "/"):
                            continue
                        if abs_url not in queued:
                            queued.add(abs_url)
                            queue.append(abs_url)
                            new_links += 1
                    if new_links:
                        logger.debug("Crawl %s: discovered %d new links from %s (queue now %d)", job_id, new_links, current_url, len(queue))

        stop_reason = "max_pages reached" if pages_crawled >= max_pages else "queue exhausted"
        logger.info(
            "Crawl %s completed: %s. crawled=%d store_failed=%d skipped_robots=%d skipped_scope=%d skipped_http=%d skipped_content=%d",
            job_id, stop_reason, pages_crawled, pages_store_failed,
            pages_skipped_robots, pages_skipped_scope, pages_skipped_http, pages_skipped_content,
        )
        final_progress = _progress()
        final_progress["pages_total"] = pages_crawled
        final_progress["stop_reason"] = stop_reason
        await jobs_store.update_job_status(
            job_id,
            "completed",
            completed=datetime.now(timezone.utc),
            progress=final_progress,
        )

    except Exception as exc:
        logger.exception("Crawl %s failed with unhandled exception after %d pages", job_id, pages_crawled)
        try:
            await jobs_store.update_job_status(
                job_id,
                "failed",
                error=str(exc),
                completed=datetime.now(timezone.utc),
            )
        except Exception:
            pass
