import secrets
from typing import Optional
from uuid import UUID

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import require_admin_jwt, require_vendor_service_key
from models import TokenPair
from services import auth as auth_svc
from storage import postgres

router = APIRouter()


class _LoginBody(BaseModel):
    email: str
    password: str


class _RefreshBody(BaseModel):
    refresh_token: str


@router.post("/v1/auth/login", response_model=TokenPair)
async def login(body: _LoginBody):
    result = await auth_svc.login(body.email, body.password)
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return result


@router.post("/v1/auth/refresh", response_model=TokenPair)
async def refresh(body: _RefreshBody):
    result = await auth_svc.refresh(body.refresh_token)
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    return result


@router.post("/v1/auth/logout", status_code=204)
async def logout(claims: dict = Depends(require_admin_jwt)):
    await auth_svc.logout(claims["sub"])


class _ImpersonateBody(BaseModel):
    email: Optional[str] = "vendor-admin"


@router.post("/v1/internal/impersonate/{tenant_id}")
async def impersonate(tenant_id: UUID, _: None = Depends(require_vendor_service_key)):
    token = auth_svc.issue_impersonation_token(str(tenant_id), "vendor-admin")
    return {"access_token": token}


class _CreateUserBody(BaseModel):
    email: str
    tenant_id: UUID
    name: Optional[str] = None


@router.delete("/v1/internal/tenants/{tenant_id}", status_code=204)
async def delete_tenant(_: None = Depends(require_vendor_service_key), tenant_id: UUID = None):
    await postgres.delete_tenant_data(tenant_id)


@router.post("/v1/internal/users", status_code=201)
async def create_user(_: None = Depends(require_vendor_service_key), body: _CreateUserBody = None):
    existing = await postgres.get_user_by_email(body.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User with this email already exists")
    temp_password = secrets.token_urlsafe(12)
    password_hash = bcrypt.hashpw(temp_password.encode(), bcrypt.gensalt()).decode()
    await postgres.create_user(body.email, password_hash, body.tenant_id)
    return {"email": body.email, "temp_password": temp_password}
