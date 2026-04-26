from __future__ import annotations

import asyncio
import logging
import os
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

_EMBEDDING_MODEL  = "text-embedding-004"
_EMBED_BATCH_SIZE = 250  # text-embedding-004 accepts up to 250 texts per call

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


_INDEX_PAGE_BATCH    = 50   # pages to accumulate before one embed+upsert round
_INDEX_CANCEL_EVERY  = 100  # cancel check every N pages


async def run_index_job(tenant_id: UUID, job_id: UUID, crawl_job_id: UUID) -> None:
    """Worker task: chunk, embed, and upsert all pages from a crawl job."""
    try:
        settings_row = await postgres.get_settings(tenant_id)
        settings = Settings(**(settings_row or {}))

        pages_total = await postgres.count_crawl_pages(crawl_job_id, tenant_id)

        total_chunks_created   = 0
        total_vectors_upserted = 0
        total_embed_tokens     = 0
        total_embed_batches    = 0
        total_pages_failed     = 0
        total_pages_vectorized = 0
        idx = 0

        def _progress() -> dict:
            return {
                "pages_indexed":    idx,
                "pages_vectorized": total_pages_vectorized,
                "pages_total":      pages_total,
                "chunks_created":   total_chunks_created,
                "vectors_upserted": total_vectors_upserted,
                "embed_tokens":     total_embed_tokens,
                "embed_batches":    total_embed_batches,
                "pages_failed":     total_pages_failed,
            }

        async def _flush(pages: list[dict]) -> None:
            """Chunk all pages, embed all chunks in one call, upsert once."""
            nonlocal total_chunks_created, total_vectors_upserted, total_embed_tokens
            nonlocal total_embed_batches, total_pages_failed, total_pages_vectorized

            # Extract + chunk every page; track which chunks belong to which page
            page_chunks: list[tuple[str, list[str]]] = []
            for page in pages:
                try:
                    text = _extract_text(page["content"])
                    chunks = _chunk_text(text, settings.chunk_size, settings.chunk_overlap)
                    page_chunks.append((page["url"], chunks))
                except Exception as exc:
                    logger.warning("Failed to chunk page %s: %s", page.get("url"), exc)
                    page_chunks.append((page["url"], []))

            # Pages with no content count as vectorized (nothing to embed)
            for _, chunks in page_chunks:
                if not chunks:
                    total_pages_vectorized += 1

            # Flatten all chunks for a single embed call
            flat_urls:   list[str] = []
            flat_chunks: list[str] = []
            for url, chunks in page_chunks:
                for chunk in chunks:
                    flat_urls.append(url)
                    flat_chunks.append(chunk)

            if not flat_chunks:
                return

            try:
                embeddings, tokens, batches = await _embed_texts(tenant_id, flat_chunks)
                total_embed_tokens  += tokens
                total_embed_batches += batches

                vectors = [
                    {
                        "id":      str(uuid.uuid4()),
                        "vector":  emb,
                        "payload": {
                            "source":       url,
                            "text":         chunk,
                            "crawl_job_id": str(crawl_job_id),
                        },
                    }
                    for url, chunk, emb in zip(flat_urls, flat_chunks, embeddings)
                ]
                await qdrant.upsert_vectors(tenant_id, vectors)
                total_vectors_upserted += len(vectors)
                total_chunks_created   += len(vectors)
                for _, chunks in page_chunks:
                    if chunks:
                        total_pages_vectorized += 1
            except Exception as exc:
                logger.warning("Embed/upsert failed for batch of %d pages: %s", len(pages), exc)
                total_pages_failed += sum(1 for _, c in page_chunks if c)

        batch: list[dict] = []
        async for page in jobs_storage.iter_crawl_pages(crawl_job_id, tenant_id):
            batch.append(page)
            if len(batch) < _INDEX_PAGE_BATCH:
                continue

            await _flush(batch)
            idx += len(batch)
            batch = []

            await jobs_storage.update_job_status(job_id, "running", progress=_progress())
            if idx % _INDEX_CANCEL_EVERY == 0:
                if await jobs_storage.is_cancel_requested(job_id):
                    logger.info("Vectorize job %s cancelled after %d pages", job_id, idx)
                    await jobs_storage.update_job_status(
                        job_id, "failed", error="Stopped by user",
                        completed=datetime.now(timezone.utc),
                    )
                    return

        if batch:
            await _flush(batch)
            idx += len(batch)

        final = _progress()
        final["pages_indexed"] = pages_total
        final["pages_total"]   = pages_total
        await jobs_storage.update_job_status(
            job_id, "completed", completed=datetime.now(timezone.utc), progress=final,
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
        await jobs_storage.update_job_status(
            job_id, "failed",
            error="Stopped by user",
            completed=datetime.now(timezone.utc),
        )


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
            embeddings = model.get_embeddings(inputs)
            batch_count += 1
            _warned_stats = False
            for e in embeddings:
                results.append(e.values)
                try:
                    tc = e.statistics.token_count
                    if tc is not None:
                        total_tokens += tc
                    elif not _warned_stats:
                        logger.warning("Vertex AI embed returned no token_count in statistics")
                        _warned_stats = True
                except Exception as stats_exc:
                    if not _warned_stats:
                        logger.warning("Could not read embed token_count: %s", stats_exc)
                        _warned_stats = True
        return results, total_tokens, batch_count

    return await asyncio.wait_for(asyncio.to_thread(_call), timeout=120.0)
