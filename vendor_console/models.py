from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class SourceBreakdown(BaseModel):
    rag: int
    curated: int
    guardrail: int
    error: int


class TenantSummary(BaseModel):
    tenant_id: UUID
    name: str
    plan: str
    questions_quota: int
    suspended: bool
    created: datetime
    quota_utilisation_pct: float
    questions_7d: int
    questions_30d: int
    source_breakdown_7d: SourceBreakdown
    error_rate_7d_pct: float
    avg_response_ms_7d: Optional[int]
    last_question_at: Optional[datetime]
    last_indexed_at: Optional[datetime]


class TenantQuota(BaseModel):
    tenant_id: UUID
    questions_quota: int
    updated_at: datetime


class PaymentEvent(BaseModel):
    event_type: str
    tenant_id: UUID
    plan: str
    questions_quota: int
