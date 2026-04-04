from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from auth import require_vendor_jwt
from models import TokenPair
from services import auth as auth_svc

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
async def logout(email: str = Depends(require_vendor_jwt)):
    await auth_svc.logout(email)
