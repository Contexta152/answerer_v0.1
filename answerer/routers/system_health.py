from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends

from auth import require_service_key
from storage.postgres import get_system_health_stats

router = APIRouter()

_ANSWERER_STARTED_AT = datetime.now(timezone.utc).isoformat()


@router.get("/v1/admin/system-health")
async def system_health(_: None = Depends(require_service_key)) -> dict:
    stats = await get_system_health_stats()

    qdrant_ok = False
    qdrant_collections: int | None = None
    try:
        qdrant_url = os.environ.get("QDRANT_URL", "")
        if qdrant_url:
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{qdrant_url}/collections")
                if r.status_code == 200:
                    qdrant_ok = True
                    qdrant_collections = len(r.json().get("result", {}).get("collections", []))
    except Exception:
        pass

    return {
        **stats,
        "answerer_started_at": _ANSWERER_STARTED_AT,
        "qdrant_ok": qdrant_ok,
        "qdrant_collections": qdrant_collections,
    }
