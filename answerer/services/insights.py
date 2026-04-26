from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from uuid import UUID

from storage.db import get_pool
from services.embed import embed_texts


async def get_insights(tenant_id: UUID, from_dt: datetime, to_dt: datetime) -> dict:
    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT question, source, timing_total_ms, chunks
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
        ORDER BY timestamp DESC LIMIT 500
        """,
        tenant_id, from_dt, to_dt,
    )

    if len(rows) < 5:
        return {"summary": {"total": len(rows), "k": 0, "silhouette": None}, "clusters": [], "low_performers": []}

    questions = [r["question"] for r in rows]

    # Embed in batches of 50
    embeddings: list[list[float]] = []
    for i in range(0, len(questions), 50):
        vecs = await embed_texts(questions[i : i + 50])
        embeddings.extend(vecs)

    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    X = np.array(embeddings, dtype=np.float32)

    max_k = min(10, len(rows) // 5)
    if max_k < 2:
        max_k = 2

    def _find_best_k(X: np.ndarray, max_k: int) -> tuple[int, float]:
        best_k, best_sc = 2, -1.0
        for k in range(2, max_k + 1):
            km = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = km.fit_predict(X)
            sc = float(silhouette_score(X, labels))
            if sc > best_sc:
                best_sc = sc
                best_k = k
        return best_k, best_sc

    best_k, best_sc = await asyncio.to_thread(_find_best_k, X, max_k)

    def _cluster(X: np.ndarray, k: int) -> np.ndarray:
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        return km.fit_predict(X)

    labels = await asyncio.to_thread(_cluster, X, best_k)

    # Group rows by cluster
    clusters_raw: dict[int, list[dict]] = {i: [] for i in range(best_k)}
    for i, row in enumerate(rows):
        clusters_raw[int(labels[i])].append(dict(row))

    # Score each cluster
    cluster_list: list[dict] = []
    for cid, members in clusters_raw.items():
        n = len(members)
        errors = sum(1 for m in members if m["source"] == "error")
        curated_count = sum(1 for m in members if m["source"] == "curated")

        total_score, score_n, low_score_n = 0.0, 0, 0
        for m in members:
            chunks = json.loads(m["chunks"]) if m["chunks"] else []
            for c in chunks:
                s = float(c.get("score", 0))
                total_score += s
                score_n += 1
                if s < 0.5:
                    low_score_n += 1

        avg_score = total_score / score_n if score_n else None
        avg_ms = int(sum(m["timing_total_ms"] or 0 for m in members) / n)

        if errors / n > 0.3 or (avg_score is not None and avg_score < 0.4):
            badge = "poor"
        elif errors / n > 0.1 or (avg_score is not None and avg_score < 0.6):
            badge = "weak"
        elif curated_count / n > 0.8:
            badge = "curated"
        else:
            badge = "good"

        cluster_list.append({
            "id":            cid,
            "n":             n,
            "badge":         badge,
            "avg_score":     round(avg_score, 3) if avg_score is not None else None,
            "avg_ms":        avg_ms,
            "error_rate_pct": round(errors / n * 100, 1),
            "low_score_pct": round(low_score_n / score_n * 100, 1) if score_n else 0,
            "sample_questions": [m["question"] for m in members[:5]],
            "label":         None,
        })

    # Label clusters in parallel
    cluster_list = await _label_clusters_parallel(cluster_list)

    # Low performers
    low_performers = []
    for row in rows:
        chunks = json.loads(row["chunks"]) if row["chunks"] else []
        avg_cs = sum(c.get("score", 0) for c in chunks) / len(chunks) if chunks else None
        if row["source"] == "error" or (avg_cs is not None and avg_cs < 0.45):
            low_performers.append({
                "question":       row["question"],
                "source":         row["source"],
                "avg_chunk_score": round(avg_cs, 3) if avg_cs is not None else None,
                "total_ms":       row["timing_total_ms"],
            })
    low_performers = low_performers[:20]

    return {
        "summary": {
            "total":      len(rows),
            "k":          best_k,
            "silhouette": round(best_sc, 3),
        },
        "clusters":       sorted(cluster_list, key=lambda x: -x["n"]),
        "low_performers": low_performers,
    }


async def _label_clusters_parallel(clusters: list[dict]) -> list[dict]:
    tasks = [_label_cluster(c["sample_questions"], c["id"]) for c in clusters]
    labels = await asyncio.gather(*tasks, return_exceptions=True)
    for cluster, label in zip(clusters, labels):
        cluster["label"] = label if isinstance(label, str) else f"Cluster {cluster['id']}"
    return clusters


async def _label_cluster(samples: list[str], cid: int) -> str:
    import vertexai
    from vertexai.generative_models import GenerativeModel

    project  = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    model_name = os.environ.get("VERTEX_LLM_MODEL", "gemini-2.0-flash-001")

    vertexai.init(project=project, location=location)
    model = GenerativeModel(model_name)

    prompt = (
        "Give a short topic label (3-6 words) for this cluster of questions:\n"
        + "\n".join(f"- {q}" for q in samples)
        + "\n\nRespond with ONLY the label, nothing else."
    )
    try:
        response = await asyncio.to_thread(model.generate_content, prompt)
        return response.text.strip()[:60]
    except Exception:
        return f"Cluster {cid}"
