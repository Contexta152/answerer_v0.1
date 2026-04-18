from __future__ import annotations

import os
from typing import Optional

import httpx

_LS_API_BASE = "https://api.lemonsqueezy.com/v1"

# Plan definitions — quotas mirror provisioning.py
# Variant IDs are set via env vars and filled in from the LS dashboard.
PLANS = [
    {
        "name":     "starter",
        "label":    "Starter",
        "quota":    1_000,
        "price":    "$29 / month",
        "features": ["1,000 questions / month", "RAG + curated answers", "Widget embed", "Email support"],
        "env_var":  "LS_VARIANT_STARTER",
    },
    {
        "name":     "growth",
        "label":    "Growth",
        "quota":    10_000,
        "price":    "$99 / month",
        "features": ["10,000 questions / month", "RAG + curated answers", "Widget embed", "Priority support"],
        "env_var":  "LS_VARIANT_GROWTH",
    },
    {
        "name":     "professional",
        "label":    "Professional",
        "quota":    50_000,
        "price":    "$299 / month",
        "features": ["50,000 questions / month", "RAG + curated answers", "Widget embed", "Dedicated support"],
        "env_var":  "LS_VARIANT_PROFESSIONAL",
    },
]


def get_plans() -> list[dict]:
    """Return plan metadata. variant_id is None if the env var is not yet set."""
    result = []
    for p in PLANS:
        result.append({
            "name":       p["name"],
            "label":      p["label"],
            "quota":      p["quota"],
            "price":      p["price"],
            "features":   p["features"],
            "configured": bool(os.environ.get(p["env_var"])),
        })
    return result


def _plan_to_variant_id(plan: str) -> Optional[str]:
    for p in PLANS:
        if p["name"] == plan:
            return os.environ.get(p["env_var"]) or None
    return None


async def create_checkout_url(plan: str) -> str:
    """
    Create a LemonSqueezy checkout for the given plan and return the URL.

    Embeds checkout_data.custom.application_name = "" so that LemonSqueezy
    renders an input field for it on the checkout form. The filled value
    arrives in meta.custom_data.application_name on the order_created webhook.
    """
    variant_id = _plan_to_variant_id(plan)
    if not variant_id:
        raise ValueError(f"No variant ID configured for plan '{plan}'")

    api_key  = os.environ["LEMONSQUEEZY_API_KEY"]
    store_id = os.environ["LEMONSQUEEZY_STORE_ID"]

    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_data": {
                    "custom": {
                        "application_name": ""
                    }
                }
            },
            "relationships": {
                "store": {
                    "data": {"type": "stores", "id": str(store_id)}
                },
                "variant": {
                    "data": {"type": "variants", "id": str(variant_id)}
                }
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(f"{_LS_API_BASE}/checkouts", json=payload, headers=headers)
        res.raise_for_status()
        return res.json()["data"]["attributes"]["url"]
