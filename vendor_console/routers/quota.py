from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import require_vendor_jwt
from services import quota as quota_svc

router = APIRouter()


class _SetQuotaBody(BaseModel):
    questions_quota: int


@router.get("/v1/tenants/{tenant_id}/quota")
async def get_quota(
    tenant_id: UUID,
    _: str = Depends(require_vendor_jwt),
):
    row = await quota_svc.get_quota(tenant_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return {"tenant_id": row["tenant_id"], "questions_quota": row["questions_quota"], "updated_at": row["updated_at"]}


@router.put("/v1/tenants/{tenant_id}/quota", status_code=204)
async def set_quota(
    tenant_id: UUID,
    body: _SetQuotaBody,
    _: str = Depends(require_vendor_jwt),
):
    if body.questions_quota < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="questions_quota must be non-negative")
    await quota_svc.set_quota(tenant_id, body.questions_quota)
