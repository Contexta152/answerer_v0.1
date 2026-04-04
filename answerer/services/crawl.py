from __future__ import annotations

import asyncio
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
) -> Job:
    tenant = await pg_store.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    active = await jobs_store.get_active_job(tenant_id, "crawl")
    if active is not None:
        raise HTTPException(
            status_code=409,
            detail="A crawl job is already running for this tenant",
        )

    job = await jobs_store.create_job(tenant_id, "crawl")
    background_tasks.add_task(_run_crawl, job.job_id, tenant_id, url, max_pages)
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


async def _run_crawl(job_id: UUID, tenant_id: UUID, seed_url: str, max_pages: int) -> None:
    """Background task: BFS crawl from seed_url, store pages, update job progress."""
    try:
        await jobs_store.update_job_status(
            job_id, "running", started=datetime.now(timezone.utc)
        )

        from urllib.parse import urljoin, urlparse

        parsed_seed = urlparse(seed_url)
        base_netloc = parsed_seed.netloc
        base_scheme = parsed_seed.scheme

        rp = await _fetch_robots(f"{base_scheme}://{base_netloc}/robots.txt")

        visited: set[str] = set()
        queue: deque[str] = deque([seed_url])
        pages_crawled = 0

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            while queue and pages_crawled < max_pages:
                if job_id in _cancel_requested:
                    _cancel_requested.discard(job_id)
                    await jobs_store.update_job_status(
                        job_id,
                        "failed",
                        error="Stopped by user",
                        completed=datetime.now(timezone.utc),
                    )
                    return

                current_url = queue.popleft()
                if current_url in visited:
                    continue
                visited.add(current_url)

                parsed = urlparse(current_url)
                if parsed.netloc != base_netloc:
                    continue
                if not rp.can_fetch(_USER_AGENT, current_url):
                    continue

                try:
                    resp = await client.get(current_url)
                except (httpx.RequestError, httpx.HTTPStatusError):
                    continue

                if resp.status_code != 200:
                    continue

                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    continue

                body = resp.text
                await jobs_store.insert_crawl_page(job_id, tenant_id, current_url, body)
                pages_crawled += 1

                await jobs_store.update_job_status(
                    job_id,
                    "running",
                    progress={"pages_crawled": pages_crawled, "pages_total": None},
                )

                if "text/html" in content_type:
                    extractor = _LinkExtractor()
                    extractor.feed(body)
                    for href in extractor.links:
                        abs_url = urljoin(current_url, href).split("#")[0]
                        p = urlparse(abs_url)
                        if (
                            p.scheme in ("http", "https")
                            and p.netloc == base_netloc
                            and abs_url not in visited
                        ):
                            queue.append(abs_url)

        await jobs_store.update_job_status(
            job_id,
            "completed",
            completed=datetime.now(timezone.utc),
            progress={"pages_crawled": pages_crawled, "pages_total": pages_crawled},
        )

    except Exception as exc:
        try:
            await jobs_store.update_job_status(
                job_id,
                "failed",
                error=str(exc),
                completed=datetime.now(timezone.utc),
            )
        except Exception:
            pass
