from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class Quota(BaseModel):
    tenant_id: UUID
    questions_quota: int
    updated_at: datetime
