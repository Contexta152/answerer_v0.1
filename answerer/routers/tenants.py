from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import require_admin_jwt, require_service_key
from models import Settings, Tenant, TenantActivitySummary, TenantCreated, Usage
from services import tenants as tenant_svc

router = APIRouter()


class _CreateTenantBody(BaseModel):
    name: str


def _not_found(code: str, message: str):
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code, "message": message},
    )


@router.get("/v1/admin/tenants/summary")
async def get_vendor_tenants_summary(
    _: None = Depends(require_service_key),
):
    items = await tenant_svc.get_vendor_tenants_summary()
    return {"items": [i.model_dump() for i in items]}


@router.post("/v1/tenants", status_code=201, response_model=TenantCreated)
async def create_tenant(
    body: _CreateTenantBody,
    _: None = Depends(require_service_key),
):
    return await tenant_svc.create_tenant(body.name)


@router.get("/v1/tenants/{tenant_id}", response_model=Tenant)
async def get_tenant(
    tenant_id: UUID,
    _: None = Depends(require_service_key),
):
    tenant = await tenant_svc.get_tenant(tenant_id)
    if tenant is None:
        _not_found("tenant_not_found", "Tenant not found")
    return tenant


@router.delete("/v1/tenants/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: UUID,
    _: None = Depends(require_service_key),
):
    found = await tenant_svc.delete_tenant(tenant_id)
    if not found:
        _not_found("tenant_not_found", "Tenant not found")


@router.get("/v1/tenants/{tenant_id}/usage", response_model=Usage)
async def get_tenant_usage(
    tenant_id: UUID,
    caller: UUID = Depends(require_admin_jwt),
):
    usage = await tenant_svc.get_tenant_usage(tenant_id)
    if usage is None:
        _not_found("tenant_not_found", "Tenant not found")
    return usage


@router.post("/v1/tenants/{tenant_id}/suspend", status_code=204)
async def suspend_tenant(
    tenant_id: UUID,
    caller: UUID = Depends(require_admin_jwt),
):
    found = await tenant_svc.suspend_tenant(tenant_id)
    if not found:
        _not_found("tenant_not_found", "Tenant not found")


@router.post("/v1/tenants/{tenant_id}/reinstate", status_code=204)
async def reinstate_tenant(
    tenant_id: UUID,
    caller: UUID = Depends(require_admin_jwt),
):
    found = await tenant_svc.reinstate_tenant(tenant_id)
    if not found:
        _not_found("tenant_not_found", "Tenant not found")


@router.get("/v1/tenants/{tenant_id}/settings", response_model=Settings)
async def get_settings(
    tenant_id: UUID,
    caller: UUID = Depends(require_admin_jwt),
):
    settings = await tenant_svc.get_settings(tenant_id)
    if settings is None:
        _not_found("tenant_not_found", "Tenant not found")
    return settings


@router.put("/v1/tenants/{tenant_id}/settings", response_model=Settings)
async def update_settings(
    tenant_id: UUID,
    body: Settings,
    caller: UUID = Depends(require_admin_jwt),
):
    settings = await tenant_svc.update_settings(tenant_id, body)
    if settings is None:
        _not_found("tenant_not_found", "Tenant not found")
    return settings
