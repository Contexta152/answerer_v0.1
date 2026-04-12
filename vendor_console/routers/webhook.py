from __future__ import annotations

import hashlib
import hmac
import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request, status

from services import provisioning
from storage import postgres

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_signature(raw_body: bytes, signature: str) -> bool:
    secret = os.environ.get("LEMONSQUEEZY_SIGNING_SECRET", "")
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/v1/webhooks/lemonsqueezy", status_code=200)
async def lemonsqueezy_webhook(
    request: Request,
    x_signature: str = Header(..., alias="X-Signature"),
):
    raw_body = await request.body()

    if not _verify_signature(raw_body, x_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = await request.json()
    event_name = payload.get("meta", {}).get("event_name")

    if event_name != "order_created":
        return {"received": True}

    attrs = payload.get("data", {}).get("attributes", {})
    if attrs.get("status") != "paid":
        return {"received": True}

    ls_order_id = str(payload["data"]["id"])
    email       = attrs.get("user_email", "")
    name        = attrs.get("user_name", email)
    variant_id  = str(attrs.get("first_order_item", {}).get("variant_id", ""))

    if not email:
        logger.warning("LS webhook order_created missing user_email, order_id=%s", ls_order_id)
        return {"received": True}

    # Idempotency — ignore duplicate deliveries
    existing = await postgres.get_ls_order(ls_order_id)
    if existing:
        logger.info("Duplicate LS webhook for order %s, skipping", ls_order_id)
        return {"received": True}

    try:
        result = await provisioning.provision_from_order(ls_order_id, email, name, variant_id)
        logger.info("Provisioned tenant %s for %s", result["tenant_id"], email)
    except Exception as exc:
        # If provisioning fails after claiming the ls_orders slot, LS will retry
        # but the idempotency check above will catch it — no duplicate tenants.
        logger.exception("Provisioning failed for order %s: %s", ls_order_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Provisioning failed")

    return {"received": True}
