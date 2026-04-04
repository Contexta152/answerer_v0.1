from __future__ import annotations

from typing import Optional
from uuid import UUID

from storage import postgres


async def get_quota(tenant_id: UUID) -> Optional[dict]:
    return await postgres.get_quota(tenant_id)


async def push_quota(tenant_id: UUID, questions_quota: int) -> dict:
    return await postgres.upsert_quota(tenant_id, questions_quota)
