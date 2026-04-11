import os
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth import require_vendor_jwt
from services import tenants as tenant_svc

router = APIRouter()


@router.get("/v1/tenants")
async def list_tenants(
    suspended: Optional[bool] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    _: str = Depends(require_vendor_jwt),
):
    return await tenant_svc.list_tenants(suspended, limit, offset)


@router.get("/v1/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: UUID,
    _: str = Depends(require_vendor_jwt),
):
    summary = await tenant_svc.get_tenant(tenant_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return summary


@router.post("/v1/internal/impersonate/{tenant_id}")
async def impersonate_tenant(tenant_id: UUID, _: str = Depends(require_vendor_jwt)):
    url = os.environ["ADMIN_CONSOLE_URL"].rstrip("/")
    key = os.environ["ADMIN_CONSOLE_SERVICE_KEY"]
    async with httpx.AsyncClient(timeout=5.0) as client:
        res = await client.post(
            f"{url}/v1/internal/impersonate/{tenant_id}",
            headers={"X-Service-Key": key},
        )
        res.raise_for_status()
        return res.json()
