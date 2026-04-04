from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel

import services.crawl as crawl_service
from auth import require_admin_jwt, require_service_key
from models import Job

router = APIRouter()


class _CrawlRequest(BaseModel):
    url: str
    max_pages: int = 500


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


@router.post("/v1/tenants/{tenant_id}/crawl", status_code=202, response_model=Job)
async def start_crawl(
    tenant_id: UUID,
    body: _CrawlRequest,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_service_key),
) -> Job:
    return await crawl_service.start_crawl(
        tenant_id, body.url, body.max_pages, background_tasks
    )


@router.get("/v1/tenants/{tenant_id}/crawl/{job_id}", response_model=Job)
async def get_crawl_status(
    tenant_id: UUID,
    job_id: UUID,
    _: None = Depends(_require_service_or_admin),
) -> Job:
    return await crawl_service.get_crawl_status(tenant_id, job_id)


@router.delete("/v1/tenants/{tenant_id}/crawl/{job_id}", status_code=204)
async def stop_crawl(
    tenant_id: UUID,
    job_id: UUID,
    _: None = Depends(_require_service_or_admin),
) -> None:
    await crawl_service.stop_crawl(tenant_id, job_id)
