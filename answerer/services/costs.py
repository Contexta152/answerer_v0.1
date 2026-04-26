from __future__ import annotations

from datetime import datetime
from uuid import UUID

from storage.db import get_pool

_EMBED_COST_PER_TOKEN  = 1.0e-7   # ~$0.025/1M chars × 4 chars/token
_LLM_INPUT_PER_TOKEN   = 1.0e-7   # $0.10/1M tokens  (Gemini 2.0 Flash)
_LLM_OUTPUT_PER_TOKEN  = 4.0e-7   # $0.40/1M tokens

# GCP infra (estimated monthly)
_VM_HOURLY_USD          = 0.0168   # e2-small
_DISK_GB                = 50
_DISK_PER_GB_MONTH      = 0.10     # pd-balanced
_CLOUD_RUN_EST_MONTH    = 3.00
_DEFAULT_BUDGET_USD     = 50.0


def _day_api_cost(prompt: int, answer: int, embed: int) -> float:
    return (
        prompt * _LLM_INPUT_PER_TOKEN
        + answer * _LLM_OUTPUT_PER_TOKEN
        + embed * _EMBED_COST_PER_TOKEN
    )


async def get_costs(tenant_id: UUID, from_dt: datetime, to_dt: datetime) -> dict:
    pool = await get_pool()

    delta_days = max((to_dt - from_dt).total_seconds() / 86400, 1)

    rows = await pool.fetch(
        """
        SELECT
            DATE_TRUNC('day', timestamp AT TIME ZONE 'UTC')::date AS day,
            SUM(COALESCE(prompt_tokens,0))  AS prompt,
            SUM(COALESCE(answer_tokens,0))  AS answer,
            SUM(COALESCE(embed_tokens,0))   AS embed,
            COUNT(*)                        AS questions
        FROM question_log
        WHERE tenant_id = $1 AND timestamp >= $2 AND timestamp <= $3
        GROUP BY 1 ORDER BY 1
        """,
        tenant_id, from_dt, to_dt,
    )

    total_prompt = sum(int(r["prompt"]) for r in rows)
    total_answer = sum(int(r["answer"]) for r in rows)
    total_embed  = sum(int(r["embed"])  for r in rows)

    api_embed  = total_embed  * _EMBED_COST_PER_TOKEN
    api_input  = total_prompt * _LLM_INPUT_PER_TOKEN
    api_output = total_answer * _LLM_OUTPUT_PER_TOKEN
    api_total  = api_embed + api_input + api_output

    vm_month       = _VM_HOURLY_USD * 24 * 30
    disk_month     = _DISK_GB * _DISK_PER_GB_MONTH
    run_month      = _CLOUD_RUN_EST_MONTH
    infra_per_day  = (vm_month + disk_month + run_month) / 30
    infra_total    = infra_per_day * delta_days

    grand_total    = api_total + infra_total
    monthly_proj   = grand_total * (30 / delta_days) if delta_days < 30 else grand_total

    by_day = []
    for r in rows:
        day_api = _day_api_cost(int(r["prompt"]), int(r["answer"]), int(r["embed"]))
        by_day.append({
            "date":      str(r["day"]),
            "api_usd":   round(day_api, 6),
            "infra_usd": round(infra_per_day, 4),
            "total_usd": round(day_api + infra_per_day, 6),
            "questions": int(r["questions"]),
        })

    return {
        "period_days":           round(delta_days, 1),
        "api": {
            "embedding_usd":     round(api_embed,  6),
            "llm_input_usd":     round(api_input,  6),
            "llm_output_usd":    round(api_output, 6),
            "total_usd":         round(api_total,  6),
        },
        "infra": {
            "vm_usd":            round(_VM_HOURLY_USD * 24 * delta_days, 4),
            "disk_usd":          round(disk_month * delta_days / 30, 4),
            "cloud_run_usd":     round(run_month * delta_days / 30, 4),
            "total_usd":         round(infra_total, 4),
        },
        "total_usd":             round(grand_total, 4),
        "projected_monthly_usd": round(monthly_proj, 2),
        "budget_usd":            _DEFAULT_BUDGET_USD,
        "by_day":                by_day,
    }
