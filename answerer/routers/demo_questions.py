from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

import services.demo_questions as demo_svc
from auth import require_admin_jwt

router = APIRouter()


class _SetRequest(BaseModel):
    questions: list[str]


@router.get("/v1/tenants/{tenant_id}/demo-questions")
async def get_demo_questions(
    tenant_id: UUID,
    caller: UUID = Depends(require_admin_jwt),
) -> dict:
    return {"questions": await demo_svc.get_demo_questions(tenant_id)}


@router.put("/v1/tenants/{tenant_id}/demo-questions")
async def set_demo_questions(
    tenant_id: UUID,
    body: _SetRequest,
    caller: UUID = Depends(require_admin_jwt),
) -> dict:
    saved = await demo_svc.set_demo_questions(tenant_id, body.questions)
    return {"questions": saved}


@router.get("/v1/public/tenants/{tenant_id}/demo-questions")
async def get_demo_questions_public(tenant_id: UUID) -> dict:
    return {"questions": await demo_svc.get_demo_questions(tenant_id)}
