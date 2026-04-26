from __future__ import annotations

from datetime import datetime
from uuid import UUID

from storage.db import get_pool

_EMBED_COST_PER_TOKEN  = 1.0e-7   # ~$0.025/1M chars × 4 chars/token
_LLM_INPUT_PER_TOKEN   = 1.0e-7   # $0.10/1M tokens  (Gemini 2.0 Flash)
_LLM_OUTPUT_PER_TOKEN  = 4.0e-7   # $0.40/1M tokens


def _entry_cost(prompt: int, answer: int, embed: int) -> float:
    return prompt * _LLM_INPUT_PER_TOKEN + answer * _LLM_OUTPUT_PER_TOKEN + embed * _EMBED_COST_PER_TOKEN


async def get_analytics(tenant_id: UUID, from_dt: datetime, to_dt: datetime) -> dict:
    pool = await get_pool()

    # ── Summary + latency + token aggregates ──────────────────────────────────
    summary = await pool.fetchrow(
        """
        SELECT
            COUNT(*)                                              AS total,
            COUNT(*) FILTER (WHERE source = 'rag')               AS rag,
            COUNT(*) FILTER (WHERE source = 'curated')           AS curated,
            COUNT(*) FILTER (WHERE source = 'guardrail')         AS guardrail,
            COUNT(*) FILTER (WHERE source = 'error')             AS error,
            PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY timing_total_ms) AS p50,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY timing_total_ms) AS p75,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY timing_total_ms) AS p95,
            PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY timing_total_ms) AS p99,
            AVG(timing_total_ms)                                  AS avg_ms,
            MAX(timing_total_ms)                                  AS max_ms,
            SUM(COALESCE(prompt_tokens, 0))                       AS prompt_total,
            SUM(COALESCE(answer_tokens, 0))                       AS answer_total,
            AVG(prompt_tokens)                                    AS avg_prompt,
            AVG(answer_tokens)                                    AS avg_answer,
            AVG(timing_embed_ms)                                  AS avg_embed_ms,
            AVG(timing_vector_search_ms)                          AS avg_vector_ms,
            AVG(timing_llm_ms)                                    AS avg_llm_ms,
            AVG(timing_curated_check_ms)                          AS avg_curated_ms,
            SUM(COALESCE(embed_tokens, 0))                        AS embed_total
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
        """,
        tenant_id, from_dt, to_dt,
    )

    total    = int(summary["total"] or 0)
    rag      = int(summary["rag"] or 0)
    curated  = int(summary["curated"] or 0)
    guardrail = int(summary["guardrail"] or 0)
    error    = int(summary["error"] or 0)

    prompt_total = int(summary["prompt_total"] or 0)
    answer_total = int(summary["answer_total"] or 0)
    embed_total  = int(summary["embed_total"] or 0)

    total_cost = _entry_cost(prompt_total, answer_total, embed_total)
    embed_usd  = embed_total * _EMBED_COST_PER_TOKEN
    input_usd  = prompt_total * _LLM_INPUT_PER_TOKEN
    output_usd = answer_total * _LLM_OUTPUT_PER_TOKEN

    delta_days = max((to_dt - from_dt).total_seconds() / 86400, 1)

    # ── Volume by day ─────────────────────────────────────────────────────────
    day_rows = await pool.fetch(
        """
        SELECT
            DATE_TRUNC('day', timestamp AT TIME ZONE 'UTC')::date  AS day,
            COUNT(*)                                               AS total,
            COUNT(*) FILTER (WHERE source='rag')                   AS rag,
            COUNT(*) FILTER (WHERE source='curated')               AS curated,
            COUNT(*) FILTER (WHERE source='guardrail')             AS guardrail,
            COUNT(*) FILTER (WHERE source='error')                 AS error,
            SUM(COALESCE(prompt_tokens,0))                         AS prompt,
            SUM(COALESCE(answer_tokens,0))                         AS answer,
            SUM(COALESCE(embed_tokens,0))                          AS embed
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
        GROUP BY 1 ORDER BY 1
        """,
        tenant_id, from_dt, to_dt,
    )

    volume_by_day = []
    for r in day_rows:
        cost = _entry_cost(int(r["prompt"]), int(r["answer"]), int(r["embed"]))
        volume_by_day.append({
            "date": str(r["day"]),
            "total": int(r["total"]),
            "rag": int(r["rag"]),
            "curated": int(r["curated"]),
            "guardrail": int(r["guardrail"]),
            "error": int(r["error"]),
            "cost": round(cost, 6),
        })

    # ── Volume by hour ────────────────────────────────────────────────────────
    hour_rows = await pool.fetch(
        """
        SELECT
            TO_CHAR(DATE_TRUNC('hour', timestamp AT TIME ZONE 'UTC'), 'YYYY-MM-DD"T"HH24') AS slot,
            COUNT(*) AS count
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
        GROUP BY 1
        """,
        tenant_id, from_dt, to_dt,
    )

    volume_by_hour = [{"slot": r["slot"], "count": int(r["count"])} for r in hour_rows]
    if volume_by_hour:
        peak = max(volume_by_hour, key=lambda x: x["count"])
        peak_slot, peak_count = peak["slot"], peak["count"]
    else:
        peak_slot, peak_count = None, 0
    volume_by_hour.sort(key=lambda x: x["slot"])

    # ── 7×24 heatmap [dow][hour] ──────────────────────────────────────────────
    hm_rows = await pool.fetch(
        """
        SELECT
            EXTRACT(DOW  FROM timestamp AT TIME ZONE 'UTC')::int AS dow,
            EXTRACT(HOUR FROM timestamp AT TIME ZONE 'UTC')::int AS hr,
            COUNT(*) AS cnt
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
        GROUP BY 1, 2
        """,
        tenant_id, from_dt, to_dt,
    )

    heatmap = [[0] * 24 for _ in range(7)]
    for r in hm_rows:
        heatmap[r["dow"]][r["hr"]] = int(r["cnt"])

    # ── Latency series (last 200 entries with timing) ─────────────────────────
    lat_rows = await pool.fetch(
        """
        SELECT timestamp, timing_total_ms, timing_embed_ms,
               timing_vector_search_ms, timing_llm_ms, timing_curated_check_ms, source
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
          AND timing_total_ms IS NOT NULL
        ORDER BY timestamp DESC LIMIT 200
        """,
        tenant_id, from_dt, to_dt,
    )

    latency_series = [
        {
            "ts":        r["timestamp"].isoformat(),
            "total_ms":  r["timing_total_ms"],
            "embed_ms":  r["timing_embed_ms"],
            "chroma_ms": r["timing_vector_search_ms"],
            "llm_ms":    r["timing_llm_ms"],
            "curated_ms": r["timing_curated_check_ms"],
            "source":    r["source"],
        }
        for r in reversed(lat_rows)
    ]

    # ── Token by day ──────────────────────────────────────────────────────────
    tok_rows = await pool.fetch(
        """
        SELECT
            DATE_TRUNC('day', timestamp AT TIME ZONE 'UTC')::date AS day,
            SUM(COALESCE(prompt_tokens,0))                         AS prompt,
            SUM(COALESCE(answer_tokens,0))                         AS answer,
            SUM(COALESCE(embed_tokens,0))                          AS embed
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
        GROUP BY 1 ORDER BY 1
        """,
        tenant_id, from_dt, to_dt,
    )

    token_by_day = []
    for r in tok_rows:
        cost = _entry_cost(int(r["prompt"]), int(r["answer"]), int(r["embed"]))
        token_by_day.append({
            "date":   str(r["day"]),
            "prompt": int(r["prompt"]),
            "answer": int(r["answer"]),
            "cost":   round(cost, 6),
        })

    # ── Chunk score histogram (20 buckets 0–1 in 0.05 steps) ─────────────────
    score_rows = await pool.fetch(
        """
        SELECT
            FLOOR(LEAST((ch->>'score')::float, 0.9999) / 0.05)::int AS bucket,
            COUNT(*) AS cnt
        FROM question_log,
             LATERAL jsonb_array_elements(COALESCE(chunks, '[]'::jsonb)) AS ch
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
          AND chunks IS NOT NULL AND jsonb_array_length(chunks) > 0
        GROUP BY 1
        """,
        tenant_id, from_dt, to_dt,
    )

    score_buckets = [0] * 20
    for r in score_rows:
        b = int(r["bucket"])
        if 0 <= b < 20:
            score_buckets[b] = int(r["cnt"])

    # ── Word count distribution ───────────────────────────────────────────────
    wc_rows = await pool.fetch(
        """
        SELECT
            CASE
                WHEN word_count BETWEEN 0  AND 4  THEN '0–4'
                WHEN word_count BETWEEN 5  AND 9  THEN '5–9'
                WHEN word_count BETWEEN 10 AND 14 THEN '10–14'
                WHEN word_count BETWEEN 15 AND 19 THEN '15–19'
                WHEN word_count BETWEEN 20 AND 29 THEN '20–29'
                ELSE '30+'
            END AS label,
            COUNT(*) AS cnt
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
        GROUP BY 1
        """,
        tenant_id, from_dt, to_dt,
    )

    wc_order = ["0–4", "5–9", "10–14", "15–19", "20–29", "30+"]
    wc_map = {r["label"]: int(r["cnt"]) for r in wc_rows}
    wc_dist = [{"label": lbl, "count": wc_map.get(lbl, 0)} for lbl in wc_order]

    # ── Slowest 10 ────────────────────────────────────────────────────────────
    slow_rows = await pool.fetch(
        """
        SELECT timestamp, question, source, timing_total_ms, timing_llm_ms, timing_embed_ms
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
          AND timing_total_ms IS NOT NULL
        ORDER BY timing_total_ms DESC LIMIT 10
        """,
        tenant_id, from_dt, to_dt,
    )

    slowest = [
        {
            "timestamp": r["timestamp"].isoformat(),
            "question":  r["question"],
            "source":    r["source"],
            "total_ms":  r["timing_total_ms"],
            "llm_ms":    r["timing_llm_ms"],
            "embed_ms":  r["timing_embed_ms"],
        }
        for r in slow_rows
    ]

    return {
        "period_start": from_dt.isoformat(),
        "period_end":   to_dt.isoformat(),
        "summary": {
            "total":           total,
            "avg_per_day":     round(total / delta_days, 2),
            "rag":             rag,
            "curated":         curated,
            "guardrail":       guardrail,
            "error":           error,
            "error_rate_pct":  round(error / total * 100, 2) if total else 0,
            "curated_rate_pct": round(curated / total * 100, 2) if total else 0,
            "total_cost_usd":  round(total_cost, 6),
            "avg_cost_usd":    round(total_cost / total, 8) if total else 0,
            "peak_slot":       peak_slot,
            "peak_count":      peak_count,
        },
        "latency": {
            "p50": int(summary["p50"] or 0),
            "p75": int(summary["p75"] or 0),
            "p95": int(summary["p95"] or 0),
            "p99": int(summary["p99"] or 0),
            "avg": int(summary["avg_ms"] or 0),
            "max": int(summary["max_ms"] or 0),
        },
        "tokens": {
            "prompt_total": prompt_total,
            "answer_total": answer_total,
            "avg_prompt":   round(float(summary["avg_prompt"] or 0), 1),
            "avg_answer":   round(float(summary["avg_answer"] or 0), 1),
        },
        "costs": {
            "embedding_usd": round(embed_usd, 6),
            "llm_input_usd": round(input_usd, 6),
            "llm_output_usd": round(output_usd, 6),
            "total_usd":     round(total_cost, 6),
        },
        "timing_avgs": {
            "embed_ms":  int(summary["avg_embed_ms"] or 0),
            "vector_ms": int(summary["avg_vector_ms"] or 0),
            "llm_ms":    int(summary["avg_llm_ms"] or 0),
            "curated_ms": int(summary["avg_curated_ms"] or 0),
        },
        "volume_by_day":  volume_by_day,
        "volume_by_hour": volume_by_hour,
        "heatmap":        heatmap,
        "latency_series": latency_series,
        "token_by_day":   token_by_day,
        "score_buckets":  score_buckets,
        "wc_dist":        wc_dist,
        "slowest":        slowest,
    }
