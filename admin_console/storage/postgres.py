from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from storage.db import get_pool as _get_pool


async def create_tables() -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admin_users (
                id UUID PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                tenant_id UUID NOT NULL,
                created TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_hash TEXT PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES admin_users(id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                created TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS quotas (
                tenant_id UUID PRIMARY KEY,
                questions_quota INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


# ── Users ─────────────────────────────────────────────────────────────────────

async def get_user_by_email(email: str) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, password_hash, tenant_id FROM admin_users WHERE email = $1",
        email,
    )
    return dict(row) if row else None


async def get_user_by_id(user_id: UUID) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, password_hash, tenant_id FROM admin_users WHERE id = $1",
        user_id,
    )
    return dict(row) if row else None


async def create_user(email: str, password_hash: str, tenant_id: UUID) -> dict:
    pool = await _get_pool()
    from uuid import uuid4
    row = await pool.fetchrow(
        "INSERT INTO admin_users (id, email, password_hash, tenant_id) VALUES ($1, $2, $3, $4) RETURNING id, email, tenant_id, created",
        uuid4(), email, password_hash, tenant_id,
    )
    return dict(row)


async def insert_user(user_id: UUID, email: str, password_hash: str, tenant_id: UUID) -> dict:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "INSERT INTO admin_users (id, email, password_hash, tenant_id) VALUES ($1, $2, $3, $4) RETURNING id, email, tenant_id, created",
        user_id, email, password_hash, tenant_id,
    )
    return dict(row)


# ── Refresh tokens ────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def insert_refresh_token(token: str, user_id: UUID, ttl_days: int = 30) -> None:
    pool = await _get_pool()
    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    await pool.execute(
        "INSERT INTO refresh_tokens (token_hash, user_id, expires_at) VALUES ($1, $2, $3)",
        _hash_token(token), user_id, expires_at,
    )


async def consume_refresh_token(token: str) -> Optional[UUID]:
    """Validate and delete a refresh token. Returns user_id if valid."""
    pool = await _get_pool()
    token_hash = _hash_token(token)
    row = await pool.fetchrow(
        "DELETE FROM refresh_tokens WHERE token_hash = $1 AND expires_at > NOW() RETURNING user_id",
        token_hash,
    )
    return row["user_id"] if row else None


async def delete_refresh_tokens_for_user(user_id: UUID) -> None:
    pool = await _get_pool()
    await pool.execute("DELETE FROM refresh_tokens WHERE user_id = $1", user_id)


# ── Quotas ────────────────────────────────────────────────────────────────────

async def get_quota(tenant_id: UUID) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT tenant_id, questions_quota, updated_at FROM quotas WHERE tenant_id = $1",
        tenant_id,
    )
    return dict(row) if row else None


async def upsert_quota(tenant_id: UUID, questions_quota: int) -> dict:
    pool = await _get_pool()
    now = datetime.now(timezone.utc)
    row = await pool.fetchrow(
        """
        INSERT INTO quotas (tenant_id, questions_quota, updated_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (tenant_id) DO UPDATE SET
            questions_quota = EXCLUDED.questions_quota,
            updated_at = EXCLUDED.updated_at
        RETURNING tenant_id, questions_quota, updated_at
        """,
        tenant_id, questions_quota, now,
    )
    return dict(row)
