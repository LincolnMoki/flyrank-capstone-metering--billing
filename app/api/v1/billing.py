import uuid
from typing import Optional
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, Header, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.stripe_service import StripeService
from app.db.session import get_db

router = APIRouter(prefix="/billing", tags=["Billing & Payments"])

class CheckoutRequest(BaseModel):
    tenant_id:uuid.UUID
    plan_id: str
    success_url: str
    cancel_url: str

class CheckoutResponse(BaseModel):
    session_id: str
    checkout_url: str

@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    status_code=status.HTTP_200_OK,
    summary="Create Stripe Checkout Session",
)
async def create_checkout(
    payload: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a Stripe Checkout Session for Subscription upgrades
    """
    service = StripeService(db)
    try:
        res = await service.create_checkout_session(
            tenant_id=payload.tenant_id,
            plan_id=payload.plan_id,
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
        )
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create checkout session: {str(e)}",
        )

@router.post(
    "/webhooks/stripe",
    status_code=status.HTTP_200_OK,
    summary="Stripe Webhook Receiver",
)
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
):
    """
    Receives raw Stripe webhook payloads, verifies signatures, and updates subscriptions.
    """
    if not stripe_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header",
        )

    payload = await request.body()
    service = StripeService(db)

    try:
        event = service.verify_webhook_signature(payload, stripe_signature)
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid webhook signature: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error verifying event: {str(e)}",
        )

    success, message = await service.handle_webhook_event(event)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return {"status": "success", "detail": message}