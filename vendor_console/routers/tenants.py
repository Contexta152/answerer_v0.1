from typing import Optional
from uuid import UUID

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
