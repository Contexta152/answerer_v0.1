from uuid import UUID

from fastapi import APIRouter, Depends

from auth import require_admin_jwt

router = APIRouter()


@router.get("/v1/tenants/{tenant_id}/analytics")
async def get_analytics(tenant_id: UUID, caller: UUID = Depends(require_admin_jwt)):
    return {}
