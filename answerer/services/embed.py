from __future__ import annotations

import asyncio
import os
from uuid import UUID

import vertexai
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

_MODEL_NAME = "text-embedding-004"
# Task type for question-to-question semantic matching (curated answers, guardrails)
_TASK_TYPE_SYMMETRIC = "SEMANTIC_SIMILARITY"
# Task type for document indexing (crawl chunks)
_TASK_TYPE_DOCUMENT = "RETRIEVAL_DOCUMENT"
# Task type for query-time embedding (ask)
_TASK_TYPE_QUERY = "RETRIEVAL_QUERY"

_model: TextEmbeddingModel | None = None


def _get_model() -> TextEmbeddingModel:
    global _model
    if _model is None:
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        vertexai.init(project=project, location=location)
        _model = TextEmbeddingModel.from_pretrained(_MODEL_NAME)
    return _model


async def embed_texts(texts: list[str], task_type: str = _TASK_TYPE_SYMMETRIC) -> list[list[float]]:
    """Embed multiple texts in one Vertex AI call."""
    model = _get_model()
    inputs = [TextEmbeddingInput(t, task_type) for t in texts]
    result = await asyncio.to_thread(model.get_embeddings, inputs)
    return [r.values for r in result]


async def embed_text(text: str, tenant_id: UUID, task_type: str = _TASK_TYPE_SYMMETRIC) -> tuple[list[float], int | None]:
    """
    Embed a single text string via Vertex AI text-embedding-004.

    Uses SEMANTIC_SIMILARITY by default — appropriate for curated questions and
    guardrail seeds where both query and document sides are questions.
    Pass task_type=RETRIEVAL_DOCUMENT for indexed content chunks.
    Pass task_type=RETRIEVAL_QUERY for ask-time query embedding.

    Returns (vector, token_count). token_count may be None if unavailable.
    """
    model = _get_model()
    inputs = [TextEmbeddingInput(text, task_type)]
    result = await asyncio.to_thread(model.get_embeddings, inputs)
    embedding = result[0]
    token_count: int | None = None
    try:
        token_count = embedding.statistics.token_count
    except Exception:
        pass
    return embedding.values, token_count
