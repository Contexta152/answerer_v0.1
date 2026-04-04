from __future__ import annotations

import secrets
from uuid import UUID, uuid4

from models import Settings, SourceBreakdown, Tenant, TenantActivitySummary, TenantCreated, Usage
from storage import postgres


async def get_vendor_tenants_summary() -> list[TenantActivitySummary]:
    rows = await postgres.get_vendor_tenants_summary()
    result = []
    for row in rows:
        quota = row["questions_quota"] or 0
        questions_30d = int(row["questions_30d"])
        questions_7d = int(row["questions_7d"])
        error_7d = int(row["error_7d"])
        quota_pct = (questions_30d / quota * 100.0) if quota > 0 else 0.0
        error_rate = (error_7d / questions_7d * 100.0) if questions_7d > 0 else 0.0
        result.append(TenantActivitySummary(
            tenant_id=row["tenant_id"],
            name=row["name"],
            suspended=row["suspended"],
            quota_utilisation_pct=quota_pct,
            questions_7d=questions_7d,
            questions_30d=questions_30d,
            source_breakdown_7d=SourceBreakdown(
                rag=int(row["rag_7d"]),
                curated=int(row["curated_7d"]),
                guardrail=int(row["guardrail_7d"]),
                error=error_7d,
            ),
            error_rate_7d_pct=error_rate,
            avg_response_ms_7d=row["avg_response_ms_7d"],
            last_question_at=row["last_question_at"],
            last_indexed_at=row["last_indexed_at"],
        ))
    return result


async def create_tenant(name: str) -> TenantCreated:
    tenant_id = uuid4()
    widget_api_key = secrets.token_urlsafe(32)
    row = await postgres.insert_tenant(tenant_id, name, widget_api_key)
    return TenantCreated(
        id=row["id"],
        name=row["name"],
        created=row["created"],
        suspended=row["suspended"],
        widget_api_key=row["widget_api_key"],
    )


async def get_tenant(tenant_id: UUID) -> Tenant | None:
    row = await postgres.get_tenant(tenant_id)
    if row is None:
        return None
    return Tenant(**row)


async def delete_tenant(tenant_id: UUID) -> bool:
    return await postgres.delete_tenant(tenant_id)


async def get_tenant_usage(tenant_id: UUID) -> Usage | None:
    row = await postgres.get_usage(tenant_id)
    if row is None:
        return None
    return Usage(**row)


async def suspend_tenant(tenant_id: UUID) -> bool:
    row = await postgres.get_tenant(tenant_id)
    if row is None:
        return False
    return await postgres.set_suspended(tenant_id, True)


async def reinstate_tenant(tenant_id: UUID) -> bool:
    row = await postgres.get_tenant(tenant_id)
    if row is None:
        return False
    return await postgres.set_suspended(tenant_id, False)


async def get_settings(tenant_id: UUID) -> Settings | None:
    row = await postgres.get_tenant(tenant_id)
    if row is None:
        return None
    settings_row = await postgres.get_settings(tenant_id)
    if settings_row is None:
        return Settings()
    return Settings(**settings_row)


async def update_settings(tenant_id: UUID, settings: Settings) -> Settings | None:
    row = await postgres.get_tenant(tenant_id)
    if row is None:
        return None
    settings_row = await postgres.upsert_settings(tenant_id, settings)
    return Settings(**settings_row)
