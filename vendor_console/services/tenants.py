from __future__ import annotations

import logging
import os
from typing import Optional
from uuid import UUID

import httpx

from models import SourceBreakdown, TenantSummary
from storage import postgres

logger = logging.getLogger(__name__)


async def _fetch_answerer_summary() -> list[dict]:
    url = os.environ.get("ANSWERER_URL", "").rstrip("/")
    key = os.environ.get("ANSWERER_SERVICE_KEY", "")
    if not url:
        logger.warning("ANSWERER_URL not configured — returning empty activity data")
        return []
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{url}/v1/admin/tenants/summary",
            headers={"X-Service-Key": key},
        )
        resp.raise_for_status()
        return resp.json().get("items", [])


def _build_summary(activity: dict, quota_row: Optional[dict], order_info: Optional[dict] = None) -> TenantSummary:
    plan = quota_row["plan"] if quota_row else "unknown"
    questions_quota = quota_row["questions_quota"] if quota_row else 0
    questions_30d = activity.get("questions_30d", 0) or 0
    questions_7d = activity.get("questions_7d", 0) or 0
    error_7d = activity.get("source_breakdown_7d", {}).get("error", 0) or 0

    quota_pct = (questions_30d / questions_quota * 100.0) if questions_quota > 0 else 0.0
    error_rate = (error_7d / questions_7d * 100.0) if questions_7d > 0 else 0.0

    # Prefer ls_orders.created_at (signup time) over tenant_created_at
    created = (
        order_info["created_at"]
        if order_info and order_info.get("created_at")
        else (quota_row["tenant_created_at"] if quota_row and quota_row.get("tenant_created_at") else "1970-01-01T00:00:00Z")
    )

    src = activity.get("source_breakdown_7d") or {}
    return TenantSummary(
        tenant_id=activity["tenant_id"],
        name=activity["name"],
        email=order_info["email"] if order_info else None,
        application_name=order_info["application_name"] if order_info else None,
        plan=plan,
        questions_quota=questions_quota,
        suspended=activity.get("suspended", False),
        created=created,
        quota_utilisation_pct=quota_pct,
        questions_7d=questions_7d,
        questions_30d=questions_30d,
        source_breakdown_7d=SourceBreakdown(
            rag=src.get("rag", 0) or 0,
            curated=src.get("curated", 0) or 0,
            guardrail=src.get("guardrail", 0) or 0,
            error=src.get("error", 0) or 0,
        ),
        error_rate_7d_pct=error_rate,
        avg_response_ms_7d=activity.get("avg_response_ms_7d"),
        last_question_at=activity.get("last_question_at"),
        last_indexed_at=activity.get("last_indexed_at"),
    )


async def list_tenants(
    suspended: Optional[bool],
    limit: int,
    offset: int,
) -> dict:
    activity_items = await _fetch_answerer_summary()
    quota_map = {r["tenant_id"]: r for r in await postgres.list_tenant_quotas()}
    order_map = await postgres.get_tenant_order_info()

    summaries = []
    for item in activity_items:
        tid = str(item["tenant_id"])
        quota_row = quota_map.get(tid) or quota_map.get(UUID(tid))
        summary = _build_summary(item, quota_row, order_info=order_map.get(tid))
        if suspended is not None and summary.suspended != suspended:
            continue
        summaries.append(summary)

    total = len(summaries)
    return {"items": [s.model_dump() for s in summaries[offset: offset + limit]], "total": total}


async def get_tenant(tenant_id: UUID) -> Optional[TenantSummary]:
    activity_items = await _fetch_answerer_summary()
    target = next((i for i in activity_items if str(i["tenant_id"]) == str(tenant_id)), None)
    if target is None:
        return None
    quota_row = await postgres.get_tenant_quota(tenant_id)
    order_map = await postgres.get_tenant_order_info()
    return _build_summary(target, quota_row, order_info=order_map.get(str(tenant_id)))
