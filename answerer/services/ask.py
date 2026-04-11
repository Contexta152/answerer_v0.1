from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

from fastapi import HTTPException

import storage.postgres as pg
import storage.qdrant as qdrant_store
from models import Chunk, QuestionLogEntry, Settings, Timing

_LLM_MODEL = os.environ.get("VERTEX_LLM_MODEL", "gemini-1.5-flash")
_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question using only the "
    "context provided below. If the context does not contain enough information, "
    "say so briefly. Do not fabricate information.\n\n"
    "Context:\n{context}"
)


def _now_ms() -> int:
    return int(time.monotonic() * 1000)


def _build_prompt(question: str, chunks: list[Chunk]) -> str:
    context = (
        "\n\n".join(f"[Source: {c.source}]\n{c.text}" for c in chunks)
        if chunks
        else "No relevant context found."
    )
    return f"{_SYSTEM_PROMPT.format(context=context)}\n\nQuestion: {question}"


def _make_log_entry(
    request_id: UUID,
    question: str,
    answer: str | None,
    source: str,
    *,
    guardrail_name: str | None = None,
    matched_question: str | None = None,
    curated_match_type: str | None = None,
    chunks: list[Chunk] | None = None,
    prompt_tokens: int | None = None,
    answer_tokens: int | None = None,
    embed_tokens: int | None = None,
    error: str | None = None,
    timing: Timing | None = None,
) -> QuestionLogEntry:
    return QuestionLogEntry(
        request_id=request_id,
        timestamp=datetime.now(timezone.utc),
        question=question,
        word_count=len(question.split()),
        source=source,
        answer=answer,
        answer_tokens=answer_tokens,
        curated_match_type=curated_match_type,
        matched_question=matched_question,
        guardrail_name=guardrail_name,
        chunks=chunks or [],
        prompt_tokens=prompt_tokens,
        embed_tokens=embed_tokens,
        error=error,
        timing=timing,
    )


def _log_async(tenant_id: UUID, entry: QuestionLogEntry) -> None:
    """Fire-and-forget: schedule a non-blocking log write."""
    asyncio.create_task(pg.insert_question_log_entry(tenant_id, entry))


async def _validate_request(tenant_id: UUID, question: str) -> Settings:
    """Check tenant is active and question is valid. Returns settings."""
    tenant = await pg.get_tenant(tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant["suspended"]:
        raise HTTPException(status_code=402, detail="Tenant suspended — quota exceeded")

    settings_row = await pg.get_settings(tenant_id)
    settings = Settings(**(settings_row or {}))

    if not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    if len(question) > settings.max_question_chars:
        raise HTTPException(
            status_code=400,
            detail=f"Question exceeds max_question_chars ({settings.max_question_chars})",
        )
    return settings


async def _generate(question: str, chunks: list[Chunk]) -> tuple[str, int | None, int | None]:
    """Call Vertex AI Gemini (non-streaming). Returns (answer, prompt_tokens, answer_tokens)."""
    import vertexai
    from vertexai.generative_models import GenerativeModel

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    prompt = _build_prompt(question, chunks)

    def _call() -> Any:
        vertexai.init(project=project, location=location)
        model = GenerativeModel(_LLM_MODEL)
        return model.generate_content(prompt)

    response = await asyncio.to_thread(_call)
    answer = response.text

    prompt_tokens = None
    answer_tokens = None
    try:
        usage = response.usage_metadata
        prompt_tokens = usage.prompt_token_count
        answer_tokens = usage.candidates_token_count
    except Exception:
        pass

    return answer, prompt_tokens, answer_tokens


async def _generate_stream(question: str, chunks: list[Chunk]) -> AsyncIterator[str]:
    """Stream Vertex AI Gemini response. Yields text deltas."""
    import vertexai
    from vertexai.generative_models import GenerativeModel

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    prompt = _build_prompt(question, chunks)

    q: asyncio.Queue[str | None | BaseException] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def _producer() -> None:
        try:
            vertexai.init(project=project, location=location)
            model = GenerativeModel(_LLM_MODEL)
            for chunk in model.generate_content(prompt, stream=True):
                try:
                    text = chunk.text
                    if text:
                        loop.call_soon_threadsafe(q.put_nowait, text)
                except Exception:
                    pass
            loop.call_soon_threadsafe(q.put_nowait, None)
        except Exception as exc:
            loop.call_soon_threadsafe(q.put_nowait, exc)

    t = threading.Thread(target=_producer, daemon=True)
    t.start()

    while True:
        item = await q.get()
        if item is None:
            break
        if isinstance(item, BaseException):
            raise item
        yield item


def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def ask(tenant_id: UUID, question: str) -> dict:
    """Non-streaming ask flow. Returns {answer, source, request_id}."""
    request_id = uuid4()
    start_ms = _now_ms()

    # 1. Validate tenant and question
    settings = await _validate_request(tenant_id, question)

    # 2. Embed question
    from services.embed import embed_text
    embed_start = _now_ms()
    vector, embed_tokens = await embed_text(question, tenant_id, task_type="RETRIEVAL_QUERY")
    embed_ms = _now_ms() - embed_start

    # 3. Guardrail check
    guardrail_start = _now_ms()
    guardrail_hits = await qdrant_store.similarity_search(
        tenant_id,
        vector,
        top_k=5,
        score_threshold=0.0,
        payload_filter={"type": "guardrail"},
    )
    guardrail_check_ms = _now_ms() - guardrail_start
    for hit in guardrail_hits:
        payload = hit["payload"]
        if not payload.get("enabled", True):
            continue
        if hit["score"] >= payload.get("threshold", 0.85):
            answer = payload["response"]
            total_ms = _now_ms() - start_ms
            _log_async(
                tenant_id,
                _make_log_entry(
                    request_id, question, answer, "guardrail",
                    guardrail_name=payload.get("name"),
                    embed_tokens=embed_tokens,
                    timing=Timing(embed_ms=embed_ms, guardrail_check_ms=guardrail_check_ms, total_ms=total_ms),
                ),
            )
            return {"answer": answer, "source": "guardrail", "request_id": str(request_id)}

    # 4. Curated answer check
    curated_start = _now_ms()
    curated_hits = await qdrant_store.similarity_search(
        tenant_id,
        vector,
        top_k=1,
        score_threshold=settings.curated_threshold,
        payload_filter={"type": "curated"},
    )
    curated_ms = _now_ms() - curated_start
    if curated_hits:
        hit = curated_hits[0]
        answer = hit["payload"]["answer"]
        total_ms = _now_ms() - start_ms
        _log_async(
            tenant_id,
            _make_log_entry(
                request_id, question, answer, "curated",
                matched_question=hit["payload"].get("question"),
                curated_match_type="semantic",
                embed_tokens=embed_tokens,
                timing=Timing(embed_ms=embed_ms, guardrail_check_ms=guardrail_check_ms, curated_check_ms=curated_ms, total_ms=total_ms),
            ),
        )
        return {"answer": answer, "source": "curated", "request_id": str(request_id)}

    # 5. RAG retrieve
    rag_start = _now_ms()
    rag_hits = await qdrant_store.similarity_search(
        tenant_id,
        vector,
        top_k=settings.top_k,
        score_threshold=settings.score_threshold,
        must_not_payload=[{"type": "guardrail"}, {"type": "curated"}],
    )
    rag_ms = _now_ms() - rag_start

    chunks = [
        Chunk(
            source=hit["payload"].get("source", ""),
            score=hit["score"],
            tokens=len(hit["payload"].get("text", "").split()),
            text=hit["payload"].get("text", ""),
        )
        for hit in rag_hits
    ]

    # 6. LLM generate
    llm_start = _now_ms()
    try:
        answer, prompt_tokens, answer_tokens = await _generate(question, chunks)
    except Exception as exc:
        total_ms = _now_ms() - start_ms
        _log_async(
            tenant_id,
            _make_log_entry(
                request_id, question, None, "error",
                error=str(exc),
                embed_tokens=embed_tokens,
                timing=Timing(
                    embed_ms=embed_ms, guardrail_check_ms=guardrail_check_ms,
                    curated_check_ms=curated_ms,
                    vector_search_ms=rag_ms, total_ms=total_ms,
                ),
            ),
        )
        raise HTTPException(status_code=500, detail=f"LLM generation failed: {exc}")
    llm_ms = _now_ms() - llm_start
    total_ms = _now_ms() - start_ms

    # 7. Log non-blocking
    _log_async(
        tenant_id,
        _make_log_entry(
            request_id, question, answer, "rag",
            chunks=chunks,
            prompt_tokens=prompt_tokens,
            answer_tokens=answer_tokens,
            embed_tokens=embed_tokens,
            timing=Timing(
                embed_ms=embed_ms,
                guardrail_check_ms=guardrail_check_ms,
                curated_check_ms=curated_ms,
                vector_search_ms=rag_ms,
                llm_ms=llm_ms,
                total_ms=total_ms,
            ),
        ),
    )

    return {"answer": answer, "source": "rag", "request_id": str(request_id)}


async def ask_stream(tenant_id: UUID, question: str) -> AsyncIterator[str]:
    """
    Streaming ask flow. Yields SSE-formatted strings.
    Event types: delta {text}, done {source, request_id}, error {code, message}.
    """
    request_id = uuid4()
    start_ms = _now_ms()

    # 1. Validate tenant and question
    tenant = await pg.get_tenant(tenant_id)
    if tenant is None:
        yield _sse_event("error", {"code": "not_found", "message": "Tenant not found"})
        return
    if tenant["suspended"]:
        yield _sse_event("error", {"code": "suspended", "message": "Tenant suspended — quota exceeded"})
        return

    settings_row = await pg.get_settings(tenant_id)
    settings = Settings(**(settings_row or {}))

    if not question.strip():
        yield _sse_event("error", {"code": "invalid_question", "message": "Question cannot be empty"})
        return
    if len(question) > settings.max_question_chars:
        yield _sse_event("error", {
            "code": "question_too_long",
            "message": f"Question exceeds max_question_chars ({settings.max_question_chars})",
        })
        return

    # 2. Embed question
    from services.embed import embed_text
    embed_start = _now_ms()
    vector, embed_tokens = await embed_text(question, tenant_id, task_type="RETRIEVAL_QUERY")
    embed_ms = _now_ms() - embed_start

    # 3. Guardrail check
    guardrail_start = _now_ms()
    guardrail_hits = await qdrant_store.similarity_search(
        tenant_id,
        vector,
        top_k=5,
        score_threshold=0.0,
        payload_filter={"type": "guardrail"},
    )
    guardrail_check_ms = _now_ms() - guardrail_start
    for hit in guardrail_hits:
        payload = hit["payload"]
        if not payload.get("enabled", True):
            continue
        if hit["score"] >= payload.get("threshold", 0.85):
            answer = payload["response"]
            total_ms = _now_ms() - start_ms
            yield _sse_event("delta", {"text": answer})
            yield _sse_event("done", {"source": "guardrail", "request_id": str(request_id)})
            _log_async(
                tenant_id,
                _make_log_entry(
                    request_id, question, answer, "guardrail",
                    guardrail_name=payload.get("name"),
                    embed_tokens=embed_tokens,
                    timing=Timing(embed_ms=embed_ms, guardrail_check_ms=guardrail_check_ms, total_ms=total_ms),
                ),
            )
            return

    # 4. Curated answer check
    curated_start = _now_ms()
    curated_hits = await qdrant_store.similarity_search(
        tenant_id,
        vector,
        top_k=1,
        score_threshold=settings.curated_threshold,
        payload_filter={"type": "curated"},
    )
    curated_ms = _now_ms() - curated_start
    if curated_hits:
        hit = curated_hits[0]
        answer = hit["payload"]["answer"]
        total_ms = _now_ms() - start_ms
        yield _sse_event("delta", {"text": answer})
        yield _sse_event("done", {"source": "curated", "request_id": str(request_id)})
        _log_async(
            tenant_id,
            _make_log_entry(
                request_id, question, answer, "curated",
                matched_question=hit["payload"].get("question"),
                curated_match_type="semantic",
                embed_tokens=embed_tokens,
                timing=Timing(embed_ms=embed_ms, guardrail_check_ms=guardrail_check_ms, curated_check_ms=curated_ms, total_ms=total_ms),
            ),
        )
        return

    # 5. RAG retrieve
    rag_start = _now_ms()
    rag_hits = await qdrant_store.similarity_search(
        tenant_id,
        vector,
        top_k=settings.top_k,
        score_threshold=settings.score_threshold,
        must_not_payload=[{"type": "guardrail"}, {"type": "curated"}],
    )
    rag_ms = _now_ms() - rag_start

    chunks = [
        Chunk(
            source=hit["payload"].get("source", ""),
            score=hit["score"],
            tokens=len(hit["payload"].get("text", "").split()),
            text=hit["payload"].get("text", ""),
        )
        for hit in rag_hits
    ]

    # 6. Stream LLM response
    llm_start = _now_ms()
    full_answer = ""
    try:
        async for text in _generate_stream(question, chunks):
            full_answer += text
            yield _sse_event("delta", {"text": text})
    except Exception as exc:
        total_ms = _now_ms() - start_ms
        yield _sse_event("error", {"code": "generation_failed", "message": str(exc)})
        _log_async(
            tenant_id,
            _make_log_entry(
                request_id, question, None, "error",
                error=str(exc),
                embed_tokens=embed_tokens,
                timing=Timing(
                    embed_ms=embed_ms, guardrail_check_ms=guardrail_check_ms,
                    curated_check_ms=curated_ms,
                    vector_search_ms=rag_ms, total_ms=total_ms,
                ),
            ),
        )
        return

    llm_ms = _now_ms() - llm_start
    total_ms = _now_ms() - start_ms

    unique_sources = list(dict.fromkeys(c.source for c in chunks if c.source))
    yield _sse_event("done", {"source": "rag", "request_id": str(request_id), "sources": unique_sources})

    # 7. Log non-blocking
    _log_async(
        tenant_id,
        _make_log_entry(
            request_id, question, full_answer, "rag",
            chunks=chunks,
            embed_tokens=embed_tokens,
            timing=Timing(
                embed_ms=embed_ms,
                guardrail_check_ms=guardrail_check_ms,
                curated_check_ms=curated_ms,
                vector_search_ms=rag_ms,
                llm_ms=llm_ms,
                total_ms=total_ms,
            ),
        ),
    )
