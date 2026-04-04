from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

import services.qlog as qlog_service
from auth import require_admin_jwt
from models import QuestionLogEntry

router = APIRouter()

_VALID_SOURCES = {"rag", "curated", "guardrail", "error"}


@router.get("/v1/tenants/{tenant_id}/qlog")
async def query_question_log(
    tenant_id: UUID,
    caller: UUID = Depends(require_admin_jwt),
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    source: Optional[str] = Query(None, enum=list(_VALID_SOURCES)),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    if caller != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Token tenant does not match resource"},
        )

    result = await qlog_service.query_question_log(
        tenant_id=tenant_id,
        from_dt=from_,
        to_dt=to,
        source=source,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [entry.model_dump(mode="json") for entry in result["items"]],
        "total": result["total"],
    }
