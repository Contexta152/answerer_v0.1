from uuid import UUID
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from services.ratelimit import check_rate_limit
from services import proxy

router = APIRouter()


class AskRequest(BaseModel):
    question: str


@router.post("/v1/ask/{tenant_id}")
async def ask(tenant_id: UUID, body: AskRequest, x_widget_key: str = Header(...)):
    check_rate_limit(str(tenant_id))
    if not body.question.strip():
        raise HTTPException(status_code=400, detail={"code": "invalid_question", "message": "Question must not be empty"})
    status, data = await proxy.ask(str(tenant_id), body.question, x_widget_key)
    return JSONResponse(content=data, status_code=status)


@router.post("/v1/ask/{tenant_id}/stream")
async def ask_stream(tenant_id: UUID, body: AskRequest, x_widget_key: str = Header(...)):
    check_rate_limit(str(tenant_id))
    if not body.question.strip():
        raise HTTPException(status_code=400, detail={"code": "invalid_question", "message": "Question must not be empty"})
    status, error_body, stream = await proxy.ask_stream(str(tenant_id), body.question, x_widget_key)
    if stream is None:
        import json
        try:
            detail = json.loads(error_body)
        except Exception:
            detail = {"code": "upstream_error", "message": error_body.decode(errors="replace")}
        return JSONResponse(content=detail, status_code=status)
    return StreamingResponse(stream, media_type="text/event-stream")
