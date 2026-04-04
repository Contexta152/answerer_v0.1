from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from auth import require_admin_jwt
from services.analytics import get_analytics

router = APIRouter()


@router.get("/v1/tenants/{tenant_id}/analytics")
async def analytics(
    tenant_id: UUID,
    from_dt: datetime = Query(..., alias="from"),
    to_dt: datetime = Query(..., alias="to"),
    caller: UUID = Depends(require_admin_jwt),
):
    return await get_analytics(tenant_id, from_dt, to_dt)
