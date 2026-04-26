from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

import services.crawl as crawl_service
from auth import require_admin_jwt, require_service_key
from models import Job

router = APIRouter()


class _CrawlRequest(BaseModel):
    url: str
    max_pages: int = 500
    max_depth: int = 3
    name: Optional[str] = None
    crawl_delay: float = 0.0


async def _require_service_or_admin(
    x_service_key: Optional[str] = Header(None, alias="X-Service-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> None:
    """Accept either a valid service key or a valid admin JWT."""
    if x_service_key is not None:
        expected = os.environ.get("SERVICE_KEY", "")
        if not expected or x_service_key != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorised"
            )
        return
    if authorization and authorization.startswith("Bearer "):
        creds = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=authorization[7:]
        )
        await require_admin_jwt(creds)
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorised"
    )


@router.get("/v1/tenants/{tenant_id}/crawls")
async def list_crawls(
    tenant_id: UUID,
    _: None = Depends(_require_service_or_admin),
):
    from storage import postgres as pg_store
    rows = await pg_store.get_crawl_jobs(tenant_id)
    import json as _json

    def _iso(v):
        return v.isoformat() if v is not None else None

    items = []
    for r in rows:
        progress = None
        if r["progress"] is not None:
            p = r["progress"]
            if isinstance(p, str):
                p = _json.loads(p)
            progress = p
        items.append({
            "job_id": str(r["job_id"]),
            "url": r["url"],
            "status": r["status"],
            "created": _iso(r["created"]),
            "completed": _iso(r.get("completed")),
            "progress": progress,
            "error": r["error"],
            "embed_tokens": r.get("embed_tokens"),
            "pages_indexed": r.get("pages_indexed"),
            "index_job_id": str(r["index_job_id"]) if r.get("index_job_id") else None,
            "index_status": r.get("index_status"),
            "index_completed": _iso(r.get("index_completed")),
            "name": r.get("name"),
        })
    return {"items": items}


@router.post("/v1/tenants/{tenant_id}/crawl", status_code=202, response_model=Job)
async def start_crawl(
    tenant_id: UUID,
    body: _CrawlRequest,
    _: None = Depends(_require_service_or_admin),
) -> Job:
    return await crawl_service.start_crawl(
        tenant_id, body.url, body.max_pages,
        name=body.name, crawl_delay=body.crawl_delay, max_depth=body.max_depth,
    )


@router.get("/v1/tenants/{tenant_id}/crawl/{job_id}", response_model=Job)
async def get_crawl_status(
    tenant_id: UUID,
    job_id: UUID,
    _: None = Depends(_require_service_or_admin),
) -> Job:
    return await crawl_service.get_crawl_status(tenant_id, job_id)


@router.post("/v1/tenants/{tenant_id}/crawl/{job_id}/stop", status_code=204)
async def stop_crawl(
    tenant_id: UUID,
    job_id: UUID,
    _: None = Depends(_require_service_or_admin),
) -> None:
    await crawl_service.stop_crawl(tenant_id, job_id)


@router.get("/v1/tenants/{tenant_id}/crawl/{job_id}/pages")
async def list_crawl_pages(
    tenant_id: UUID,
    job_id: UUID,
    _: None = Depends(_require_service_or_admin),
):
    from storage.jobs import get_crawl_page_urls
    rows = await get_crawl_page_urls(job_id, tenant_id)
    return {"items": [{"url": r["url"], "crawled_at": r["crawled_at"].isoformat() if r["crawled_at"] else None} for r in rows]}


@router.delete("/v1/tenants/{tenant_id}/crawl/{job_id}", status_code=204)
async def delete_crawl(
    tenant_id: UUID,
    job_id: UUID,
    _: None = Depends(_require_service_or_admin),
) -> None:
    await crawl_service.delete_crawl(tenant_id, job_id)
