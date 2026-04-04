from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import services.curated as curated_service
from auth import require_admin_jwt
from models import CuratedAnswer

router = APIRouter()


class _CreateRequest(BaseModel):
    question: str
    answer: str


class _UpdateRequest(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None


@router.get("/v1/tenants/{tenant_id}/curated")
async def list_curated_answers(
    tenant_id: UUID,
    caller: UUID = Depends(require_admin_jwt),
) -> dict:
    items = await curated_service.list_curated_answers(tenant_id)
    return {"items": [i.model_dump() for i in items]}


@router.post("/v1/tenants/{tenant_id}/curated", status_code=201, response_model=CuratedAnswer)
async def create_curated_answer(
    tenant_id: UUID,
    body: _CreateRequest,
    caller: UUID = Depends(require_admin_jwt),
) -> CuratedAnswer:
    return await curated_service.create_curated_answer(
        tenant_id, body.question, body.answer
    )


@router.put(
    "/v1/tenants/{tenant_id}/curated/{curated_id}", response_model=CuratedAnswer
)
async def update_curated_answer(
    tenant_id: UUID,
    curated_id: UUID,
    body: _UpdateRequest,
    caller: UUID = Depends(require_admin_jwt),
) -> CuratedAnswer:
    return await curated_service.update_curated_answer(
        tenant_id, curated_id, body.question, body.answer
    )


@router.delete("/v1/tenants/{tenant_id}/curated/{curated_id}", status_code=204)
async def delete_curated_answer(
    tenant_id: UUID,
    curated_id: UUID,
    caller: UUID = Depends(require_admin_jwt),
) -> None:
    await curated_service.delete_curated_answer(tenant_id, curated_id)
