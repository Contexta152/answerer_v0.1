from uuid import UUID
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services import proxy

router = APIRouter()


@router.get("/v1/demo-questions/{tenant_id}")
async def get_demo_questions(tenant_id: UUID):
    status, data = await proxy.get_demo_questions(str(tenant_id))
    return JSONResponse(content=data, status_code=status)
