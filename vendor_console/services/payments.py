from __future__ import annotations

import logging
import os
from uuid import UUID

import httpx

from models import PaymentEvent
from services.quota import _push_to_admin_console
from storage import postgres

logger = logging.getLogger(__name__)


async def _fetch_tenant_created_at(tenant_id: UUID) -> str | None:
    url = os.environ.get("ANSWERER_URL", "").rstrip("/")
    key = os.environ.get("ANSWERER_SERVICE_KEY", "")
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{url}/v1/tenants/{tenant_id}",
                headers={"X-Service-Key": key},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json().get("created")
    except Exception:
        logger.warning("Failed to fetch tenant %s from Answerer", tenant_id, exc_info=True)
        return None


async def handle_payment_event(event: PaymentEvent) -> None:
    if event.event_type not in {
        "subscription_created", "subscription_renewed", "plan_changed", "subscription_cancelled"
    }:
        raise ValueError(f"Unknown event_type: {event.event_type}")

    existing = await postgres.get_tenant_quota(event.tenant_id)
    created_at = existing["tenant_created_at"] if existing and existing.get("tenant_created_at") else None

    if created_at is None:
        created_at = await _fetch_tenant_created_at(event.tenant_id)

    await postgres.upsert_tenant_quota(
        event.tenant_id,
        event.plan,
        event.questions_quota,
        created_at,
    )
    await _push_to_admin_console(event.tenant_id, event.questions_quota)
