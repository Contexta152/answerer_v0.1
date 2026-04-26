from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import require_admin_jwt
from services.recommendations import get_recommendations

router = APIRouter()


class _DateRange(BaseModel):
    date_from: datetime
    date_to: datetime


@router.post("/v1/tenants/{tenant_id}/recommendations")
async def recommendations(
    tenant_id: UUID,
    body: _DateRange,
    caller: UUID = Depends(require_admin_jwt),
):
    if caller != tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    return await get_recommendations(tenant_id, body.date_from, body.date_to)
