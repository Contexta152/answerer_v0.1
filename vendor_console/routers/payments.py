from fastapi import APIRouter, Depends, HTTPException, status

from auth import require_payment_service_key
from models import PaymentEvent
from services import payments as payments_svc

router = APIRouter()


@router.post("/v1/internal/payments", status_code=204)
async def receive_payment_event(
    event: PaymentEvent,
    _: None = Depends(require_payment_service_key),
):
    try:
        await payments_svc.handle_payment_event(event)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
