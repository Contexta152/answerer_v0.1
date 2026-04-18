from __future__ import annotations

from uuid import UUID

from storage import postgres

MAX = 5


async def get_demo_questions(tenant_id: UUID) -> list[str]:
    return await postgres.get_demo_questions(tenant_id)


async def set_demo_questions(tenant_id: UUID, questions: list[str]) -> list[str]:
    cleaned = [q.strip() for q in questions if q.strip()][:MAX]
    await postgres.set_demo_questions(tenant_id, cleaned)
    return cleaned
