from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from uuid import UUID

from storage.db import get_pool
from services.embed import embed_texts


async def get_gaplist(tenant_id: UUID, from_dt: datetime, to_dt: datetime) -> dict:
    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT question, chunks
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
          AND source = 'rag'
          AND chunks IS NOT NULL AND jsonb_array_length(chunks) > 0
        ORDER BY timestamp DESC LIMIT 400
        """,
        tenant_id, from_dt, to_dt,
    )

    if len(rows) < 5:
        return {"total_analyzed": len(rows), "low_score_count": 0, "gaps": []}

    # Score each question by average chunk score
    scored = []
    for row in rows:
        chunks = json.loads(row["chunks"]) if row["chunks"] else []
        avg = sum(c.get("score", 0) for c in chunks) / len(chunks) if chunks else 0.0
        scored.append({"question": row["question"], "avg_score": avg})

    low = [s for s in scored if s["avg_score"] < 0.55]
    if len(low) < 3:
        return {"total_analyzed": len(rows), "low_score_count": len(low), "gaps": []}

    questions = [s["question"] for s in low]

    embeddings: list[list[float]] = []
    for i in range(0, len(questions), 50):
        vecs = await embed_texts(questions[i : i + 50])
        embeddings.extend(vecs)

    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    X = np.array(embeddings, dtype=np.float32)
    max_k = min(8, len(low) // 3)
    if max_k < 2:
        max_k = 2

    def _fit(X: np.ndarray, max_k: int) -> tuple[int, np.ndarray]:
        best_k, best_sc, best_labels = 2, -1.0, None
        for k in range(2, max_k + 1):
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            lbl = km.fit_predict(X)
            sc = float(silhouette_score(X, lbl))
            if sc > best_sc:
                best_sc = sc
                best_k  = k
                best_labels = lbl
        if best_labels is None:
            km = KMeans(n_clusters=2, random_state=42, n_init=10)
            best_labels = km.fit_predict(X)
        return best_k, best_labels

    best_k, labels = await asyncio.to_thread(_fit, X, max_k)

    clusters: dict[int, list[dict]] = {i: [] for i in range(best_k)}
    for i, item in enumerate(low):
        clusters[int(labels[i])].append(item)

    label_tasks = [
        _label_gap([m["question"] for m in members[:5]], cid)
        for cid, members in clusters.items()
    ]
    gap_labels = await asyncio.gather(*label_tasks, return_exceptions=True)

    gaps = []
    for idx, (cid, members) in enumerate(clusters.items()):
        avg_gap = sum(m["avg_score"] for m in members) / len(members)
        lbl = gap_labels[idx] if isinstance(gap_labels[idx], str) else f"Gap {cid}"
        gaps.append({
            "id":              cid,
            "label":           lbl,
            "volume":          len(members),
            "avg_score":       round(avg_gap, 3),
            "gap_score":       round((1 - avg_gap) * len(members), 2),
            "sample_questions": [m["question"] for m in members[:5]],
        })

    gaps.sort(key=lambda x: -x["gap_score"])
    return {"total_analyzed": len(rows), "low_score_count": len(low), "gaps": gaps}


async def _label_gap(questions: list[str], cid: int) -> str:
    import vertexai
    from vertexai.generative_models import GenerativeModel

    project    = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location   = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    model_name = os.environ.get("VERTEX_LLM_MODEL", "gemini-2.0-flash-001")

    vertexai.init(project=project, location=location)
    model = GenerativeModel(model_name)

    prompt = (
        "These questions have poor retrieval scores, suggesting a content gap.\n"
        "Give a short topic label (3–6 words) for what's missing:\n"
        + "\n".join(f"- {q}" for q in questions)
        + "\n\nRespond with ONLY the label."
    )
    try:
        resp = await asyncio.to_thread(model.generate_content, prompt)
        return resp.text.strip()[:60]
    except Exception:
        return f"Gap {cid}"
