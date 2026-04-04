from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import require_admin_jwt
from models import Guardrail
from services import guardrails as guardrail_svc

router = APIRouter()


class _CreateGuardrailBody(BaseModel):
    name: str
    seeds: list[str]
    response: str
    threshold: float


class _UpdateGuardrailBody(BaseModel):
    name: str | None = None
    seeds: list[str] | None = None
    response: str | None = None
    threshold: float | None = None
    enabled: bool | None = None


def _not_found() -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "guardrail_not_found", "message": "Guardrail not found"},
    )


@router.get("/v1/tenants/{tenant_id}/guardrails")
async def list_guardrails(
    tenant_id: UUID,
    caller: UUID = Depends(require_admin_jwt),
):
    items = await guardrail_svc.list_guardrails(tenant_id)
    return {"items": [g.model_dump() for g in items]}


@router.post("/v1/tenants/{tenant_id}/guardrails", status_code=201, response_model=Guardrail)
async def create_guardrail(
    tenant_id: UUID,
    body: _CreateGuardrailBody,
    caller: UUID = Depends(require_admin_jwt),
):
    return await guardrail_svc.create_guardrail(
        tenant_id,
        name=body.name,
        seeds=body.seeds,
        response=body.response,
        threshold=body.threshold,
    )


@router.put(
    "/v1/tenants/{tenant_id}/guardrails/{guardrail_id}",
    response_model=Guardrail,
)
async def update_guardrail(
    tenant_id: UUID,
    guardrail_id: UUID,
    body: _UpdateGuardrailBody,
    caller: UUID = Depends(require_admin_jwt),
):
    # Only pass fields explicitly set in the request body
    fields = body.model_dump(exclude_none=True)
    result = await guardrail_svc.update_guardrail(tenant_id, guardrail_id, **fields)
    if result is None:
        _not_found()
    return result


@router.delete(
    "/v1/tenants/{tenant_id}/guardrails/{guardrail_id}",
    status_code=204,
)
async def delete_guardrail(
    tenant_id: UUID,
    guardrail_id: UUID,
    caller: UUID = Depends(require_admin_jwt),
):
    found = await guardrail_svc.delete_guardrail(tenant_id, guardrail_id)
    if not found:
        _not_found()
