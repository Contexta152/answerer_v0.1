from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class Error(BaseModel):
    code: str
    message: str
    detail: Optional[dict[str, Any]] = None


class Tenant(BaseModel):
    id: UUID
    name: str
    created: datetime
    suspended: bool


class TenantCreated(Tenant):
    widget_api_key: str


class Usage(BaseModel):
    period_start: datetime
    period_end: datetime
    questions_asked: int
    questions_quota: int
    tokens_used: int
    suspended: bool


class Settings(BaseModel):
    top_k: int = 8
    score_threshold: float = 0.0
    curated_threshold: float = 0.92
    max_question_chars: int = 1500
    chunk_size: int = 200
    chunk_overlap: int = 60


class Guardrail(BaseModel):
    id: UUID
    name: str
    seeds: list[str]
    response: str
    threshold: float
    enabled: bool
    created: datetime


class CuratedAnswer(BaseModel):
    id: UUID
    question: str
    answer: str
    created: datetime


class Chunk(BaseModel):
    source: str
    score: float
    tokens: int
    text: str


class Timing(BaseModel):
    curated_check_ms: Optional[int] = None
    guardrail_check_ms: Optional[int] = None
    embed_ms: Optional[int] = None
    vector_search_ms: Optional[int] = None
    llm_ms: Optional[int] = None
    total_ms: Optional[int] = None


class QuestionLogEntry(BaseModel):
    request_id: UUID
    timestamp: datetime
    question: str
    word_count: int
    source: Optional[str] = None  # rag | curated | guardrail | error
    answer: Optional[str] = None
    answer_tokens: Optional[int] = None
    curated_match_type: Optional[str] = None
    matched_question: Optional[str] = None
    guardrail_name: Optional[str] = None
    chunks: list[Chunk] = []
    prompt_tokens: Optional[int] = None
    embed_tokens: Optional[int] = None
    error: Optional[str] = None
    timing: Optional[Timing] = None


class JobProgress(BaseModel):
    pages_crawled: Optional[int] = None
    pages_indexed: Optional[int] = None
    pages_total: Optional[int] = None
    chunks_created: Optional[int] = None
    vectors_upserted: Optional[int] = None
    embed_tokens: Optional[int] = None
    embed_batches: Optional[int] = None
    pages_failed: Optional[int] = None


class Job(BaseModel):
    job_id: UUID
    status: str  # pending | running | completed | failed
    created: datetime
    started: Optional[datetime] = None
    completed: Optional[datetime] = None
    error: Optional[str] = None
    progress: Optional[JobProgress] = None
    url: Optional[str] = None
    name: Optional[str] = None


class SourceBreakdown(BaseModel):
    rag: int
    curated: int
    guardrail: int
    error: int


class TenantActivitySummary(BaseModel):
    tenant_id: UUID
    name: str
    suspended: bool
    quota_utilisation_pct: float
    questions_7d: int
    questions_30d: int
    source_breakdown_7d: SourceBreakdown
    error_rate_7d_pct: float
    avg_response_ms_7d: Optional[int] = None
    last_question_at: Optional[datetime] = None
    last_indexed_at: Optional[datetime] = None
