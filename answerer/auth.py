from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

_bearer = HTTPBearer(auto_error=False)
_ALGORITHM = "HS256"


async def require_service_key(x_service_key: Optional[str] = Header(None, alias="X-Service-Key")) -> None:
    expected = os.environ.get("SERVICE_KEY")
    if not expected or x_service_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing service key")


async def require_admin_jwt(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> UUID:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="JWT_SECRET not configured")
    try:
        payload = jwt.decode(credentials.credentials, secret, algorithms=[_ALGORITHM])
        tenant_id_str = payload.get("tenant_id")
        if not tenant_id_str:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing tenant_id claim")
        return UUID(tenant_id_str)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def require_widget_key(x_widget_key: Optional[str] = Header(None, alias="X-Widget-Key")) -> UUID:
    from storage import postgres
    if not x_widget_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing widget key")
    tenant_id = await postgres.validate_widget_key(x_widget_key)
    if tenant_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid widget key")
    return tenant_id
