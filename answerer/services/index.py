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

_EMBEDDING_MODEL = "text-embedding-004"
_EMBED_BATCH_SIZE = 20  # Keep total tokens per request well under the 20k limit


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

    return await jobs_storage.create_job(tenant_id, "index")


async def run_index_job(tenant_id: UUID, job_id: UUID, crawl_job_id: UUID) -> None:
    """Background task: chunk, embed, and upsert all pages from a crawl job."""
    await jobs_storage.update_job_status(
        job_id, "running", started=datetime.now(timezone.utc)
    )
    try:
        settings_row = await postgres.get_settings(tenant_id)
        settings = Settings(**(settings_row or {}))

        pages = await jobs_storage.get_crawl_pages(crawl_job_id, tenant_id)
        pages_total = len(pages)

        for idx, page in enumerate(pages, start=1):
            text = _extract_text(page["content"])
            chunks = _chunk_text(text, settings.chunk_size, settings.chunk_overlap)
            if not chunks:
                continue

            embeddings = await _embed_texts(tenant_id, chunks)

            vectors = [
                {
                    "id": str(uuid.uuid4()),
                    "vector": embedding,
                    "payload": {"source": page["url"], "text": chunk},
                }
                for chunk, embedding in zip(chunks, embeddings)
            ]
            await qdrant.upsert_vectors(tenant_id, vectors)

            await jobs_storage.update_job_status(
                job_id,
                "running",
                progress={"pages_indexed": idx, "pages_total": pages_total},
            )

        await jobs_storage.update_job_status(
            job_id,
            "completed",
            completed=datetime.now(timezone.utc),
            progress={"pages_indexed": pages_total, "pages_total": pages_total},
        )
    except Exception as exc:
        logger.exception("Index job %s failed for tenant %s", job_id, tenant_id)
        await jobs_storage.update_job_status(job_id, "failed", error=str(exc))


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


async def _embed_texts(tenant_id: UUID, texts: list[str]) -> list[list[float]]:
    """Embed a list of texts via Vertex AI, returning one float vector per text."""
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

    def _call() -> list[list[float]]:
        vertexai.init(project=project, location=location)
        model = TextEmbeddingModel.from_pretrained(_EMBEDDING_MODEL)
        results: list[list[float]] = []
        for i in range(0, len(texts), _EMBED_BATCH_SIZE):
            batch = texts[i : i + _EMBED_BATCH_SIZE]
            inputs = [
                TextEmbeddingInput(text=t, task_type="RETRIEVAL_DOCUMENT")
                for t in batch
            ]
            embeddings = model.get_embeddings(inputs)
            results.extend(e.values for e in embeddings)
        return results

    return await asyncio.to_thread(_call)
