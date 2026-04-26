from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from uuid import UUID

from storage.db import get_pool


async def get_recommendations(tenant_id: UUID, from_dt: datetime, to_dt: datetime) -> dict:
    pool = await get_pool()

    stats = await pool.fetchrow(
        """
        SELECT
            COUNT(*)                                              AS total,
            COUNT(*) FILTER (WHERE source='error')               AS errors,
            COUNT(*) FILTER (WHERE source='guardrail')           AS guardrail,
            COUNT(*) FILTER (WHERE source='curated')             AS curated,
            ROUND(AVG(timing_total_ms))                          AS avg_ms,
            PERCENTILE_CONT(0.95) WITHIN GROUP
                (ORDER BY timing_total_ms)                       AS p95_ms,
            ROUND(AVG(prompt_tokens))                            AS avg_prompt,
            ROUND(AVG(answer_tokens))                            AS avg_answer,
            ROUND(AVG(COALESCE(answer_tokens,0)
                      + COALESCE(prompt_tokens,0)))              AS avg_total_tokens
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
        """,
        tenant_id, from_dt, to_dt,
    )

    # Low-score RAG questions sample
    low_rows = await pool.fetch(
        """
        SELECT question, chunks
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
          AND source = 'rag'
          AND chunks IS NOT NULL AND jsonb_array_length(chunks) > 0
        ORDER BY timestamp DESC LIMIT 200
        """,
        tenant_id, from_dt, to_dt,
    )

    low_qs: list[str] = []
    for row in low_rows:
        chunks = json.loads(row["chunks"]) if row["chunks"] else []
        avg = sum(c.get("score", 0) for c in chunks) / len(chunks) if chunks else 1.0
        if avg < 0.55:
            low_qs.append(row["question"])

    total = int(stats["total"] or 0)
    signals = {
        "total_questions":     total,
        "error_rate_pct":      round(int(stats["errors"] or 0) / max(total, 1) * 100, 1),
        "guardrail_rate_pct":  round(int(stats["guardrail"] or 0) / max(total, 1) * 100, 1),
        "curated_rate_pct":    round(int(stats["curated"] or 0) / max(total, 1) * 100, 1),
        "avg_latency_ms":      int(stats["avg_ms"] or 0),
        "p95_latency_ms":      int(stats["p95_ms"] or 0),
        "avg_prompt_tokens":   int(stats["avg_prompt"] or 0),
        "avg_answer_tokens":   int(stats["avg_answer"] or 0),
        "low_score_sample":    low_qs[:10],
        "low_score_count":     len(low_qs),
    }

    recs = await _generate(signals)
    return {"signals": signals, "recommendations": recs}


async def _generate(signals: dict) -> list[dict]:
    import vertexai
    from vertexai.generative_models import GenerativeModel

    project    = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location   = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    model_name = os.environ.get("VERTEX_LLM_MODEL", "gemini-2.0-flash-001")

    vertexai.init(project=project, location=location)
    model = GenerativeModel(model_name)

    prompt = f"""You are an expert at optimizing RAG (Retrieval-Augmented Generation) systems.

Analyze the quality signals below and return 3–5 actionable recommendations as a JSON array.
Each item must have:
  "title":        short title (5–8 words)
  "description":  1–2 sentence explanation
  "impact":       "high" | "medium" | "low"
  "action":       one of: increase_top_k | lower_score_threshold | add_curated | improve_content | add_guardrail | reduce_chunk_size | manual
  "action_param": optional numeric value (e.g. the new top_k to set)

Quality signals:
{json.dumps(signals, indent=2)}

Return ONLY a valid JSON array, no markdown fences or other text."""

    try:
        resp = await asyncio.to_thread(model.generate_content, prompt)
        text = resp.text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
        recs = json.loads(text)
        if isinstance(recs, list):
            return recs
    except Exception:
        pass

    # Fallback heuristic recommendations
    recs = []
    if signals["error_rate_pct"] > 10:
        recs.append({
            "title":       "Expand knowledge base content",
            "description": f"{signals['error_rate_pct']}% of questions returned errors — your content may not cover key topics.",
            "impact":      "high",
            "action":      "improve_content",
        })
    if signals["low_score_count"] > 20:
        recs.append({
            "title":       "Lower the score threshold",
            "description": f"{signals['low_score_count']} questions returned low-score chunks. Reducing the threshold may improve coverage.",
            "impact":      "medium",
            "action":      "lower_score_threshold",
            "action_param": 0.0,
        })
    if signals["p95_latency_ms"] > 5000:
        recs.append({
            "title":       "Reduce top-k to cut latency",
            "description": f"P95 latency is {signals['p95_latency_ms']}ms. Fetching fewer chunks can speed up responses.",
            "impact":      "medium",
            "action":      "increase_top_k",
            "action_param": 5,
        })
    return recs
