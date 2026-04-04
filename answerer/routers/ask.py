from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import require_widget_key
from services import ask as ask_service

router = APIRouter()


class AskRequest(BaseModel):
    question: str


@router.post("/v1/tenants/{tenant_id}/ask")
async def ask(
    tenant_id: UUID,
    body: AskRequest,
    caller_tenant_id: UUID = Depends(require_widget_key),
):
    if caller_tenant_id != tenant_id:
        raise HTTPException(status_code=401, detail="Widget key does not belong to this tenant")
    return await ask_service.ask(tenant_id, body.question)


@router.post("/v1/tenants/{tenant_id}/ask/stream")
async def ask_stream(
    tenant_id: UUID,
    body: AskRequest,
    caller_tenant_id: UUID = Depends(require_widget_key),
):
    if caller_tenant_id != tenant_id:
        raise HTTPException(status_code=401, detail="Widget key does not belong to this tenant")
    return StreamingResponse(
        ask_service.ask_stream(tenant_id, body.question),
        media_type="text/event-stream",
    )
