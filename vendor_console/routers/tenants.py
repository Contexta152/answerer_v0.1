import os
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status

from pydantic import BaseModel

from auth import require_vendor_jwt
from models import CreateTenantRequest
from services import provisioning, tenants as tenant_svc
from storage import postgres


class _SystemPromptBody(BaseModel):
    system_prompt: Optional[str] = None

router = APIRouter()

_GCP_PROJECT  = "project-3a1ab238-6b95-4034-8c6"
_GCP_LOCATION = "us-central1"
_ROLLOUT_ALLOWED = {"answerer", "worker", "admin-console"}


async def _gcp_token() -> str:
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(
            "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
            headers={"Metadata-Flavor": "Google"},
        )
        r.raise_for_status()
        return r.json()["access_token"]


@router.post("/v1/services/{service_name}/rollout")
async def rollout_service(service_name: str, _: str = Depends(require_vendor_jwt)):
    if service_name not in _ROLLOUT_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    try:
        token = await _gcp_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.patch(
                f"https://run.googleapis.com/v2/projects/{_GCP_PROJECT}/locations/{_GCP_LOCATION}/services/{service_name}",
                headers={"Authorization": f"Bearer {token}"},
                params={"updateMask": "traffic"},
                json={"traffic": [{"type": "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST", "percent": 100}]},
            )
            if not res.is_success:
                raise HTTPException(status_code=502, detail=res.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True}


@router.get("/v1/orders")
async def list_orders(_: str = Depends(require_vendor_jwt)):
    orders = await postgres.get_orders()
    return {"orders": [
        {**{k: v for k, v in o.items() if k not in ("tenant_id", "created_at")},
         "tenant_id": str(o["tenant_id"]),
         "created_at": o["created_at"].isoformat() if o["created_at"] else None}
        for o in orders
    ]}


@router.get("/v1/tenants")
async def list_tenants(
    suspended: Optional[bool] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    _: str = Depends(require_vendor_jwt),
):
    return await tenant_svc.list_tenants(suspended, limit, offset)


@router.get("/v1/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: UUID,
    _: str = Depends(require_vendor_jwt),
):
    summary = await tenant_svc.get_tenant(tenant_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return summary


@router.post("/v1/tenants", status_code=201)
async def create_tenant(
    body: CreateTenantRequest,
    _: str = Depends(require_vendor_jwt),
):
    quota = body.questions_quota if body.questions_quota is not None else provisioning._plan_to_quota(body.plan)
    try:
        result = await provisioning.provision_enterprise(
            name=body.name,
            email=body.email,
            application_name=body.application_name,
            plan=body.plan,
            questions_quota=quota,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Provisioning failed: {exc}")
    return {
        "tenant_id": result["tenant_id"],
        "email": result["email"],
        "temp_password": result["temp_password"],
        "plan": body.plan,
        "questions_quota": quota,
    }


@router.delete("/v1/tenants/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: UUID,
    _: str = Depends(require_vendor_jwt),
):
    answerer_url = os.environ["ANSWERER_URL"].rstrip("/")
    answerer_key = os.environ["ANSWERER_SERVICE_KEY"]
    admin_url    = os.environ["ADMIN_CONSOLE_URL"].rstrip("/")
    admin_key    = os.environ["ADMIN_CONSOLE_SERVICE_KEY"]
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Wipe answerer data (postgres cascade + Qdrant + question_log)
        res = await client.delete(
            f"{answerer_url}/v1/tenants/{tenant_id}",
            headers={"X-Service-Key": answerer_key},
        )
        if res.status_code not in (204, 404):
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Answerer delete failed: {res.status_code}")
        # 2. Wipe admin-console user + quota
        res = await client.delete(
            f"{admin_url}/v1/internal/tenants/{tenant_id}",
            headers={"X-Service-Key": admin_key},
        )
        if res.status_code not in (204, 404):
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Admin console delete failed: {res.status_code}")
    # 3. Wipe vendor-console quota (orders preserved per policy)
    await postgres.delete_tenant_quota(tenant_id)


@router.post("/v1/tenants/{tenant_id}/reset-password")
async def reset_tenant_password(tenant_id: UUID, _: str = Depends(require_vendor_jwt)):
    url = os.environ["ADMIN_CONSOLE_URL"].rstrip("/")
    key = os.environ["ADMIN_CONSOLE_SERVICE_KEY"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            f"{url}/v1/internal/tenants/{tenant_id}/reset-password",
            headers={"X-Service-Key": key},
        )
        if res.status_code == 404:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No admin user found for tenant")
        res.raise_for_status()
        return res.json()


@router.get("/v1/tenants/{tenant_id}/system-prompt")
async def get_system_prompt(tenant_id: UUID, _: str = Depends(require_vendor_jwt)):
    answerer_url = os.environ["ANSWERER_URL"].rstrip("/")
    answerer_key = os.environ["ANSWERER_SERVICE_KEY"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(
            f"{answerer_url}/v1/tenants/{tenant_id}/system-prompt",
            headers={"X-Service-Key": answerer_key},
        )
    if res.status_code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    res.raise_for_status()
    return res.json()


@router.put("/v1/tenants/{tenant_id}/system-prompt")
async def upsert_system_prompt(tenant_id: UUID, body: _SystemPromptBody, _: str = Depends(require_vendor_jwt)):
    answerer_url = os.environ["ANSWERER_URL"].rstrip("/")
    answerer_key = os.environ["ANSWERER_SERVICE_KEY"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.put(
            f"{answerer_url}/v1/tenants/{tenant_id}/system-prompt",
            headers={"X-Service-Key": answerer_key, "Content-Type": "application/json"},
            json=body.model_dump(),
        )
    if res.status_code == 422:
        detail = res.json().get("detail", "Invalid prompt")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
    res.raise_for_status()
    return res.json()


@router.get("/v1/system-health")
async def system_health(_: str = Depends(require_vendor_jwt)):
    answerer_url = os.environ["ANSWERER_URL"].rstrip("/")
    answerer_key = os.environ["ANSWERER_SERVICE_KEY"]
    async with httpx.AsyncClient(timeout=8.0) as client:
        res = await client.get(
            f"{answerer_url}/v1/admin/system-health",
            headers={"X-Service-Key": answerer_key},
        )
    res.raise_for_status()
    return res.json()


@router.post("/v1/internal/impersonate/{tenant_id}")
async def impersonate_tenant(tenant_id: UUID, _: str = Depends(require_vendor_jwt)):
    url = os.environ["ADMIN_CONSOLE_URL"].rstrip("/")
    key = os.environ["ADMIN_CONSOLE_SERVICE_KEY"]
    async with httpx.AsyncClient(timeout=5.0) as client:
        res = await client.post(
            f"{url}/v1/internal/impersonate/{tenant_id}",
            headers={"X-Service-Key": key},
        )
        res.raise_for_status()
        return res.json()
