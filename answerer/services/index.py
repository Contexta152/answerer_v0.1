from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from uuid import UUID

import vertexai
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

from models import Job, Settings
from storage import jobs as jobs_storage
from storage import postgres
from storage import qdrant

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "text-embedding-004"
_EMBED_BATCH_SIZE = 20  # Keep total tokens per request well under the 20k limit

_embed_model: "TextEmbeddingModel | None" = None
_embed_model_lock = asyncio.Lock()


async def _get_embed_model() -> "TextEmbeddingModel":
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    async with _embed_model_lock:
        if _embed_model is not None:
            return _embed_model
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

        def _init():
            vertexai.init(project=project, location=location)
            return TextEmbeddingModel.from_pretrained(_EMBEDDING_MODEL)

        _embed_model = await asyncio.to_thread(_init)
        return _embed_model


class _TextExtractor(HTMLParser):
    """Strip HTML tags and return visible text content."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _extract_text(html: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        pass
    return extractor.get_text()


# ── Public interface ──────────────────────────────────────────────────────────

async def start_index(tenant_id: UUID, crawl_job_id: UUID) -> Job:
    """
    Validate preconditions, create a pending index job, and return it.
    The caller is responsible for scheduling run_index_job as a background task.

    Raises:
        KeyError("crawl_job_not_found")     — crawl job does not belong to tenant
        ValueError("crawl_job_not_completed") — crawl job is not in completed status
        RuntimeError("index_job_already_running") — a pending/running index job exists
    """
    crawl_job = await jobs_storage.get_job(tenant_id, crawl_job_id)
    if crawl_job is None:
        raise KeyError("crawl_job_not_found")
    if crawl_job.status != "completed":
        raise ValueError("crawl_job_not_completed")

    active = await jobs_storage.get_active_job(tenant_id, "index")
    if active is not None:
        raise RuntimeError("index_job_already_running")

    return await jobs_storage.create_job(tenant_id, "index", url=str(crawl_job_id))


async def run_index_job(tenant_id: UUID, job_id: UUID, crawl_job_id: UUID) -> None:
    """Worker task: chunk, embed, and upsert all pages from a crawl job."""
    try:
        settings_row = await postgres.get_settings(tenant_id)
        settings = Settings(**(settings_row or {}))

        pages_total = await postgres.count_crawl_pages(crawl_job_id, tenant_id)

        total_chunks_created = 0
        total_vectors_upserted = 0
        total_embed_tokens = 0
        total_embed_batches = 0
        total_pages_failed = 0
        total_pages_vectorized = 0
        idx = 0

        async for page in jobs_storage.iter_crawl_pages(crawl_job_id, tenant_id):
            idx += 1
            if await jobs_storage.is_cancel_requested(job_id):
                logger.info("Vectorize job %s cancelled after %d pages", job_id, idx - 1)
                await jobs_storage.update_job_status(
                    job_id, "failed",
                    error="Stopped by user",
                    completed=datetime.now(timezone.utc),
                )
                return

            try:
                text = _extract_text(page["content"])
                chunks = _chunk_text(text, settings.chunk_size, settings.chunk_overlap)
            except Exception as page_exc:
                logger.warning("Failed to extract/chunk page %s: %s", page.get("url"), page_exc)
                total_pages_failed += 1
                await jobs_storage.update_job_status(
                    job_id, "running",
                    progress={
                        "pages_indexed": idx,
                        "pages_vectorized": total_pages_vectorized,
                        "pages_total": pages_total,
                        "chunks_created": total_chunks_created,
                        "vectors_upserted": total_vectors_upserted,
                        "embed_tokens": total_embed_tokens,
                        "embed_batches": total_embed_batches,
                        "pages_failed": total_pages_failed,
                    },
                )
                continue

            if not chunks:
                await jobs_storage.update_job_status(
                    job_id, "running",
                    progress={
                        "pages_indexed": idx,
                        "pages_vectorized": total_pages_vectorized,
                        "pages_total": pages_total,
                        "chunks_created": total_chunks_created,
                        "vectors_upserted": total_vectors_upserted,
                        "embed_tokens": total_embed_tokens,
                        "embed_batches": total_embed_batches,
                        "pages_failed": total_pages_failed,
                    },
                )
                continue

            try:
                embeddings, batch_tokens, batch_count = await _embed_texts(tenant_id, chunks)

                vectors = [
                    {
                        "id": str(uuid.uuid4()),
                        "vector": embedding,
                        "payload": {
                            "source": page["url"],
                            "text": chunk,
                            "crawl_job_id": str(crawl_job_id),
                        },
                    }
                    for chunk, embedding in zip(chunks, embeddings)
                ]
                await qdrant.upsert_vectors(tenant_id, vectors)

                total_chunks_created += len(chunks)
                total_vectors_upserted += len(vectors)
                total_embed_tokens += batch_tokens
                total_embed_batches += batch_count
                total_pages_vectorized += 1
            except Exception as page_exc:
                logger.warning("Failed to embed/upsert page %s: %s", page.get("url"), page_exc)
                total_pages_failed += 1

            await jobs_storage.update_job_status(
                job_id,
                "running",
                progress={
                    "pages_indexed": idx,
                    "pages_vectorized": total_pages_vectorized,
                    "pages_total": pages_total,
                    "chunks_created": total_chunks_created,
                    "vectors_upserted": total_vectors_upserted,
                    "embed_tokens": total_embed_tokens,
                    "embed_batches": total_embed_batches,
                    "pages_failed": total_pages_failed,
                },
            )

        await jobs_storage.update_job_status(
            job_id,
            "completed",
            completed=datetime.now(timezone.utc),
            progress={
                "pages_indexed": pages_total,
                "pages_vectorized": total_pages_vectorized,
                "pages_total": pages_total,
                "chunks_created": total_chunks_created,
                "vectors_upserted": total_vectors_upserted,
                "embed_tokens": total_embed_tokens,
                "embed_batches": total_embed_batches,
                "pages_failed": total_pages_failed,
            },
        )
    except Exception as exc:
        logger.exception("Index job %s failed for tenant %s", job_id, tenant_id)
        await jobs_storage.update_job_status(job_id, "failed", error=str(exc))


async def stop_index(tenant_id: UUID, job_id: UUID) -> None:
    job = await jobs_storage.get_job(tenant_id, job_id)
    if job is None:
        raise KeyError("index_job_not_found")
    if job.status in ("pending", "running"):
        await jobs_storage.request_cancel(job_id)


async def get_index_status(tenant_id: UUID, job_id: UUID) -> Job:
    """
    Raises:
        KeyError("index_job_not_found") — job does not exist or belongs to another tenant
    """
    job = await jobs_storage.get_job(tenant_id, job_id)
    if job is None:
        raise KeyError("index_job_not_found")
    return job


# ── Internal helpers ──────────────────────────────────────────────────────────

def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Word-based sliding-window chunker.
    chunk_size and chunk_overlap are word counts (matching Settings defaults).
    """
    words = text.split()
    if not words:
        return []
    step = max(1, chunk_size - chunk_overlap)
    chunks = []
    start = 0
    while start < len(words):
        chunks.append(" ".join(words[start : start + chunk_size]))
        start += step
    return chunks


async def _embed_texts(tenant_id: UUID, texts: list[str]) -> tuple[list[list[float]], int, int]:
    """
    Embed a list of texts via Vertex AI, returning (vectors, total_tokens, batch_count).
    total_tokens is the sum of token counts across all batches (0 if unavailable).
    batch_count is the number of Vertex AI API calls made.
    """
    model = await _get_embed_model()

    def _call() -> tuple[list[list[float]], int, int]:
        results: list[list[float]] = []
        total_tokens = 0
        batch_count = 0
        for i in range(0, len(texts), _EMBED_BATCH_SIZE):
            batch = texts[i : i + _EMBED_BATCH_SIZE]
            inputs = [
                TextEmbeddingInput(text=t, task_type="RETRIEVAL_DOCUMENT")
                for t in batch
            ]
            last_exc: Exception | None = None
            for attempt in range(5):
                try:
                    embeddings = model.get_embeddings(inputs)
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < 4:
                        delay = 2 ** attempt
                        logger.warning("Embed attempt %d failed, retrying in %ds: %s", attempt + 1, delay, exc)
                        time.sleep(delay)
            if last_exc is not None:
                raise last_exc
            batch_count += 1
            for e in embeddings:
                results.append(e.values)
                try:
                    total_tokens += e.statistics.token_count
                except Exception:
                    pass
            time.sleep(0.5)
        return results, total_tokens, batch_count

    return await asyncio.wait_for(asyncio.to_thread(_call), timeout=120.0)
