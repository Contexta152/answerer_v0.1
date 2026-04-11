from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

import storage.qdrant as qdrant_store
from auth import require_admin_jwt
from services.embed import embed_text

router = APIRouter()


class SearchRequest(BaseModel):
    question: str
    top_k: int = 20


@router.post("/v1/tenants/{tenant_id}/search")
async def search_snippets(
    tenant_id: UUID,
    body: SearchRequest,
    caller: UUID = Depends(require_admin_jwt),
):
    """Return raw knowledge-base chunks (no guardrails/curated) with scores.
    Threshold is not applied server-side so the client can filter live."""
    if caller != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Token tenant does not match resource"},
        )
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    vector, embed_tokens = await embed_text(body.question, tenant_id, task_type="RETRIEVAL_QUERY")

    hits = await qdrant_store.similarity_search(
        tenant_id,
        vector,
        top_k=body.top_k,
        score_threshold=0.0,
        must_not_payload=[{"type": "guardrail"}, {"type": "curated"}],
    )

    chunks = [
        {
            "source": hit["payload"].get("source", ""),
            "score": hit["score"],
            "tokens": len(hit["payload"].get("text", "").split()),
            "text": hit["payload"].get("text", ""),
        }
        for hit in hits
    ]

    return {"chunks": chunks, "embed_tokens": embed_tokens}
