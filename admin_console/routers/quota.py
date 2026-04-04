from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import require_admin_jwt, require_vendor_service_key
from models import Quota
from services import quota as quota_svc

router = APIRouter()


class _PushQuotaBody(BaseModel):
    questions_quota: int


@router.get("/v1/quota", response_model=Quota)
async def get_quota(claims: dict = Depends(require_admin_jwt)):
    tenant_id = UUID(claims["tenant_id"])
    row = await quota_svc.get_quota(tenant_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No quota has been set for this tenant yet")
    return row


@router.put("/v1/internal/quota/{tenant_id}", status_code=204)
async def push_quota(
    tenant_id: UUID,
    body: _PushQuotaBody,
    _: None = Depends(require_vendor_service_key),
):
    if body.questions_quota < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="questions_quota must be non-negative")
    await quota_svc.push_quota(tenant_id, body.questions_quota)
