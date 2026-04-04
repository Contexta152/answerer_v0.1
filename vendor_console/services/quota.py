from __future__ import annotations

import logging
import os
from typing import Optional
from uuid import UUID

import httpx

from storage import postgres

logger = logging.getLogger(__name__)


async def _push_to_admin_console(tenant_id: UUID, questions_quota: int) -> None:
    url = os.environ.get("ADMIN_CONSOLE_URL", "").rstrip("/")
    key = os.environ.get("ADMIN_CONSOLE_SERVICE_KEY", "")
    if not url:
        logger.info("ADMIN_CONSOLE_URL not configured — skipping quota push for tenant %s", tenant_id)
        return
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.put(
                f"{url}/v1/internal/quota/{tenant_id}",
                json={"questions_quota": questions_quota},
                headers={"X-Service-Key": key},
            )
            resp.raise_for_status()
    except Exception:
        logger.warning("Failed to push quota to Admin Console for tenant %s", tenant_id, exc_info=True)


async def get_quota(tenant_id: UUID) -> Optional[dict]:
    return await postgres.get_tenant_quota(tenant_id)


async def set_quota(tenant_id: UUID, questions_quota: int) -> None:
    row = await postgres.get_tenant_quota(tenant_id)
    plan = row["plan"] if row else "unknown"
    created_at = row["tenant_created_at"] if row else None
    await postgres.upsert_tenant_quota(tenant_id, plan, questions_quota, created_at)
    await _push_to_admin_console(tenant_id, questions_quota)
