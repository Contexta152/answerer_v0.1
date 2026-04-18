from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from services import checkout as checkout_svc

logger = logging.getLogger(__name__)

router = APIRouter()


class CheckoutRequest(BaseModel):
    plan: str


class CheckoutResponse(BaseModel):
    url: str


@router.get("/v1/checkout/plans")
async def list_plans():
    """Return available plans for the checkout page."""
    return {"plans": checkout_svc.get_plans()}


@router.post("/v1/checkout", response_model=CheckoutResponse, status_code=200)
async def create_checkout(body: CheckoutRequest):
    """
    Create a LemonSqueezy checkout for the given plan name.
    Returns a checkout URL that includes the application_name custom field.
    """
    try:
        url = await checkout_svc.create_checkout_url(body.plan)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        logger.exception("Failed to create LS checkout for plan %s: %s", body.plan, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create checkout with LemonSqueezy",
        )
    return CheckoutResponse(url=url)
