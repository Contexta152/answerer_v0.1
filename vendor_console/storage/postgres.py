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
            CREATE TABLE IF NOT EXISTS vendor_users (
                id UUID PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_hash TEXT PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES vendor_users(id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                created TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tenant_quotas (
                tenant_id UUID PRIMARY KEY,
                plan TEXT NOT NULL DEFAULT 'unknown',
                questions_quota INTEGER NOT NULL DEFAULT 0,
                tenant_created_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)


# ── Users ────────────────────────────────────────────────────────────────────

async def get_user_by_email(email: str) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, password_hash FROM vendor_users WHERE email = $1",
        email,
    )
    return dict(row) if row else None


async def get_user_by_id(user_id: UUID) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, password_hash FROM vendor_users WHERE id = $1",
        user_id,
    )
    return dict(row) if row else None


async def insert_user(user_id: UUID, email: str, password_hash: str) -> dict:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "INSERT INTO vendor_users (id, email, password_hash) VALUES ($1, $2, $3) RETURNING id, email, created",
        user_id, email, password_hash,
    )
    return dict(row)


# ── Refresh tokens ───────────────────────────────────────────────────────────

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


# ── Tenant quotas ────────────────────────────────────────────────────────────

async def get_tenant_quota(tenant_id: UUID) -> Optional[dict]:
    pool = await _get_pool()
    row = await pool.fetchrow(
        "SELECT tenant_id, plan, questions_quota, updated_at FROM tenant_quotas WHERE tenant_id = $1",
        tenant_id,
    )
    return dict(row) if row else None


async def upsert_tenant_quota(
    tenant_id: UUID,
    plan: str,
    questions_quota: int,
    tenant_created_at: Optional[datetime] = None,
) -> dict:
    pool = await _get_pool()
    now = datetime.now(timezone.utc)
    row = await pool.fetchrow(
        """
        INSERT INTO tenant_quotas (tenant_id, plan, questions_quota, tenant_created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (tenant_id) DO UPDATE SET
            plan = EXCLUDED.plan,
            questions_quota = EXCLUDED.questions_quota,
            tenant_created_at = COALESCE(EXCLUDED.tenant_created_at, tenant_quotas.tenant_created_at),
            updated_at = EXCLUDED.updated_at
        RETURNING tenant_id, plan, questions_quota, tenant_created_at, updated_at
        """,
        tenant_id, plan, questions_quota, tenant_created_at, now,
    )
    return dict(row)


async def list_tenant_quotas() -> list[dict]:
    pool = await _get_pool()
    rows = await pool.fetch("SELECT tenant_id, plan, questions_quota, tenant_created_at, updated_at FROM tenant_quotas")
    return [dict(r) for r in rows]
