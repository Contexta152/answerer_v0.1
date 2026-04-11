from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional
from uuid import UUID, uuid4

import httpx

from storage import postgres

logger = logging.getLogger(__name__)

# Map LemonSqueezy variant IDs to internal plan names and quotas.
# Update these with real variant IDs from your LS dashboard.
_VARIANT_TO_PLAN: dict[str, str] = {}
_PLAN_TO_QUOTA: dict[str, int] = {
    "starter":      1_000,
    "growth":      10_000,
    "professional": 50_000,
}
_DEFAULT_PLAN = "starter"
_DEFAULT_QUOTA = 1_000


def _variant_to_plan(variant_id: Optional[str]) -> str:
    return _VARIANT_TO_PLAN.get(str(variant_id), _DEFAULT_PLAN)


def _plan_to_quota(plan: str) -> int:
    return _PLAN_TO_QUOTA.get(plan, _DEFAULT_QUOTA)


async def _create_answerer_tenant(tenant_id: UUID, name: str) -> dict:
    url = os.environ["ANSWERER_URL"].rstrip("/")
    key = os.environ["ANSWERER_SERVICE_KEY"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            f"{url}/v1/tenants",
            json={"id": str(tenant_id), "name": name},
            headers={"X-Service-Key": key},
        )
        res.raise_for_status()
        return res.json()


async def _create_admin_user(tenant_id: UUID, email: str, name: Optional[str]) -> dict:
    url = os.environ["ADMIN_CONSOLE_URL"].rstrip("/")
    key = os.environ["ADMIN_CONSOLE_SERVICE_KEY"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            f"{url}/v1/internal/users",
            json={"email": email, "tenant_id": str(tenant_id), "name": name},
            headers={"X-Service-Key": key},
        )
        res.raise_for_status()
        return res.json()


async def _push_quota(tenant_id: UUID, quota: int, plan: str) -> None:
    url = os.environ["ADMIN_CONSOLE_URL"].rstrip("/")
    key = os.environ["ADMIN_CONSOLE_SERVICE_KEY"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.put(
            f"{url}/v1/internal/quota/{tenant_id}",
            json={"questions_quota": quota},
            headers={"X-Service-Key": key},
        )
        res.raise_for_status()
    await postgres.upsert_tenant_quota(tenant_id, plan, quota)


async def provision_from_order(
    ls_order_id: str,
    email: str,
    name: str,
    variant_id: Optional[str],
) -> dict:
    tenant_id = uuid4()
    plan = _variant_to_plan(variant_id)
    quota = _plan_to_quota(plan)

    answerer_result, admin_result = await asyncio.gather(
        _create_answerer_tenant(tenant_id, name),
        _create_admin_user(tenant_id, email, name),
    )

    await _push_quota(tenant_id, quota, plan)
    await postgres.insert_ls_order(ls_order_id, tenant_id, email, name, variant_id, plan)

    # TODO: replace with real transactional email
    print(f"[EMAIL STUB] tenant_id={tenant_id} email={email} temp_password={admin_result['temp_password']}", flush=True)
    logger.info("[EMAIL STUB] tenant_id=%s email=%s temp_password=%s", tenant_id, email, admin_result["temp_password"])

    return {"tenant_id": str(tenant_id), "email": email}
