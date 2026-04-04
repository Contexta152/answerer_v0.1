from __future__ import annotations

import os
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

_bearer = HTTPBearer(auto_error=False)
_ALGORITHM = "HS256"


async def require_payment_service_key(
    x_service_key: Optional[str] = Header(None, alias="X-Service-Key"),
) -> None:
    expected = os.environ.get("PAYMENT_SERVICE_KEY")
    if not expected or x_service_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing service key")


async def require_vendor_jwt(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    """Validates the vendor JWT and returns the user email (sub claim)."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    secret = os.environ.get("VENDOR_JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="VENDOR_JWT_SECRET not configured")
    try:
        payload = jwt.decode(credentials.credentials, secret, algorithms=[_ALGORITHM])
        sub = payload.get("sub")
        if not sub or payload.get("role") != "vendor":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token claims")
        return sub
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
