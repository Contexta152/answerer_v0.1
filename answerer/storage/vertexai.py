from __future__ import annotations

import asyncio
import os
from typing import Optional

import vertexai
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

_model: Optional[TextEmbeddingModel] = None


def _get_model() -> TextEmbeddingModel:
    global _model
    if _model is None:
        project = os.environ["GOOGLE_CLOUD_PROJECT"]
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        vertexai.init(project=project, location=location)
        _model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    return _model


async def embed_texts(
    texts: list[str],
    task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[list[float]]:
    """Return one embedding vector per input text."""
    model = _get_model()
    inputs = [TextEmbeddingInput(text=t, task_type=task_type) for t in texts]
    embeddings = await asyncio.to_thread(model.get_embeddings, inputs)
    return [list(e.values) for e in embeddings]
