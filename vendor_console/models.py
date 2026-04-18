from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


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
    email: Optional[str] = None
    application_name: Optional[str] = None
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


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
    application_name: str = Field(..., min_length=1, max_length=200)
    plan: Literal["starter", "growth", "professional"]
    questions_quota: Optional[int] = Field(None, ge=0)
