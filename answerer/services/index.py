from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
import re

from bs4 import BeautifulSoup
from uuid import UUID

import vertexai
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

from models import Job, Settings
from storage import jobs as jobs_storage
from storage import postgres
from storage import qdrant

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL   = "text-embedding-004"
_EMBED_MAX_TEXTS   = 250        # hard API limit: texts per call
_EMBED_MAX_TOKENS  = 18_000     # soft ceiling: 10% headroom under the 20k token limit
_EMBED_TOKENS_PER_WORD = 1.5    # conservative estimate; retry-with-halving handles any remaining overruns

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


_BS_DECOMPOSE = [
    "script", "style", "nav", "header", "footer",
    "aside", "noscript", "form", "svg", "iframe",
]


def _extract_text(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(_BS_DECOMPOSE):
            tag.decompose()
        return soup.get_text(separator="\n\n", strip=True)
    except Exception:
        return ""


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
                sample_url = pages[0].get("url", "?") if pages else "?"
                sample_text = _extract_text(pages[0]["content"])[:200] if pages else ""
                sample_html = pages[0]["content"][:200] if pages else ""
                logger.warning(
                    "Index job: batch of %d pages produced no text chunks. "
                    "First page: %s | extracted: %r | html_start: %r",
                    len(pages), sample_url, sample_text, sample_html,
                )
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

_SENTENCE_END_RE = re.compile(r'(?<=[.!?])\s+')


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END_RE.split(text) if s.strip()]


def _last_n_words(text: str, n: int) -> str:
    if n <= 0:
        return ""
    words = text.split()
    return " ".join(words[-n:]) if len(words) > n else text


def _word_sliding_window(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Word-based fallback for oversized single sentences — original chunker behaviour."""
    words = text.split()
    if not words:
        return []
    step = max(1, chunk_size - chunk_overlap)
    chunks, start = [], 0
    while start < len(words):
        chunks.append(" ".join(words[start : start + chunk_size]))
        start += step
    return chunks


def _split_paragraph(para: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Sentence-boundary splitting for a paragraph that exceeds chunk_size words."""
    sentences = _split_sentences(para)
    if not sentences:
        return _word_sliding_window(para, chunk_size, chunk_overlap)

    result: list[str] = []
    current: list[str] = []
    current_words = 0
    prefix = ""

    for sentence in sentences:
        s_words = len(sentence.split())

        if s_words > chunk_size:
            if current:
                flushed = (prefix + " " if prefix else "") + " ".join(current)
                result.append(flushed.strip())
                prefix = _last_n_words(flushed, chunk_overlap)
                current, current_words = [], 0
            sub = _word_sliding_window(sentence, chunk_size, chunk_overlap)
            if sub and prefix:
                sub[0] = (prefix + " " + sub[0]).strip()
            result.extend(sub)
            prefix = _last_n_words(sub[-1], chunk_overlap) if sub else prefix
            continue

        if current_words + s_words <= chunk_size:
            current.append(sentence)
            current_words += s_words
        else:
            flushed = (prefix + " " if prefix else "") + " ".join(current)
            result.append(flushed.strip())
            prefix = _last_n_words(flushed, chunk_overlap)
            current, current_words = [sentence], s_words

    if current:
        flushed = (prefix + " " if prefix else "") + " ".join(current)
        result.append(flushed.strip())

    return [c for c in result if c]


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Hierarchical chunker: paragraph → sentence → word fallback.
    chunk_size and chunk_overlap are word counts (matching Settings defaults).
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    result: list[str] = []
    current: list[str] = []
    current_words = 0

    for para in paragraphs:
        p_words = len(para.split())
        if p_words == 0:
            continue

        if p_words > chunk_size:
            if current:
                result.append(" ".join(current))
                current, current_words = [], 0
            result.extend(_split_paragraph(para, chunk_size, chunk_overlap))
        elif current_words + p_words <= chunk_size:
            current.append(para)
            current_words += p_words
        else:
            result.append(" ".join(current))
            current, current_words = [para], p_words

    if current:
        result.append(" ".join(current))

    return [c for c in result if c]


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

        def _embed_batch(batch: list[str]) -> None:
            nonlocal total_tokens, batch_count
            inputs = [TextEmbeddingInput(text=t, task_type="RETRIEVAL_DOCUMENT") for t in batch]
            try:
                embeddings = model.get_embeddings(inputs)
            except Exception as exc:
                if "token" in str(exc).lower() and len(batch) > 1:
                    logger.warning("Embed token limit exceeded (batch=%d), splitting in half", len(batch))
                    mid = len(batch) // 2
                    _embed_batch(batch[:mid])
                    _embed_batch(batch[mid:])
                    return
                raise
            batch_count += 1
            warned = False
            for e in embeddings:
                results.append(e.values)
                try:
                    stats = e.statistics
                    if stats is not None and stats.token_count is not None:
                        total_tokens += stats.token_count
                    elif not warned:
                        logger.warning("Vertex AI embed: token_count unavailable in statistics")
                        warned = True
                except Exception as stats_exc:
                    if not warned:
                        logger.warning("Could not read embed token_count: %s", stats_exc)
                        warned = True

        batch: list[str] = []
        batch_tokens = 0
        for text in texts:
            est = max(1, int(len(text.split()) * _EMBED_TOKENS_PER_WORD))
            if batch and (len(batch) >= _EMBED_MAX_TEXTS or batch_tokens + est > _EMBED_MAX_TOKENS):
                _embed_batch(batch)
                batch = []
                batch_tokens = 0
            batch.append(text)
            batch_tokens += est
        if batch:
            _embed_batch(batch)

        return results, total_tokens, batch_count

    return await asyncio.wait_for(asyncio.to_thread(_call), timeout=120.0)
