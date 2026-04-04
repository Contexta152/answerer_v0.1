from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
from jose import jwt

from storage import postgres

_ALGORITHM = "HS256"
_ACCESS_TOKEN_TTL_SECONDS = 3600


def _issue_access_token(email: str) -> str:
    secret = os.environ["VENDOR_JWT_SECRET"]
    payload = {
        "sub": email,
        "role": "vendor",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=_ACCESS_TOKEN_TTL_SECONDS),
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def _issue_refresh_token() -> str:
    return secrets.token_urlsafe(48)


async def login(email: str, password: str) -> dict | None:
    user = await postgres.get_user_by_email(email)
    if user is None or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return None
    access_token = _issue_access_token(email)
    refresh_token = _issue_refresh_token()
    await postgres.insert_refresh_token(refresh_token, user["id"])
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": _ACCESS_TOKEN_TTL_SECONDS,
    }


async def refresh(refresh_token: str) -> dict | None:
    user_id = await postgres.consume_refresh_token(refresh_token)
    if user_id is None:
        return None
    user = await postgres.get_user_by_id(user_id)
    if user is None:
        return None
    new_access = _issue_access_token(user["email"])
    new_refresh = _issue_refresh_token()
    await postgres.insert_refresh_token(new_refresh, user_id)
    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "expires_in": _ACCESS_TOKEN_TTL_SECONDS,
    }


async def logout(email: str) -> None:
    user = await postgres.get_user_by_email(email)
    if user:
        await postgres.delete_refresh_tokens_for_user(user["id"])


async def create_vendor_user(email: str, password: str) -> dict:
    """Utility — called once at bootstrap to seed the initial vendor admin account."""
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    return await postgres.insert_user(uuid4(), email, password_hash)
