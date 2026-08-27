import uuid
from typing import Optional
from app.core.config import settings
from fastapi import APIRouter, Depends, HTTPException, Request, Header, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.flutterwave_service import FlutterwaveService
from app.db.session import get_db

router = APIRouter()

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
    summary="Create Flutterwave Checkout Session",
)
async def create_checkout(
    payload: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a Flutterwave hosted payment session.
    """

    service = FlutterwaveService(db)

    try:
        return await service.create_checkout_session(
            tenant_id=payload.tenant_id,
            plan_id=payload.plan_id,
            success_url=payload.success_url,
            cancel_url=payload.cancel_url,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create checkout session: {str(e)}",
        )


@router.post(
    "/webhooks/flutterwave",
    status_code=status.HTTP_200_OK,
    summary="Flutterwave Webhook Receiver",
)
async def flutterwave_webhook(
    request: Request,
    verif_hash: Optional[str] = Header(
        None,
        alias="verif-hash",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Receives and verifies Flutterwave webhook events.
    """

    if not verif_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Flutterwave webhook signature",
        )

    if verif_hash != settings.FLW_SECRET_HASH:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Flutterwave webhook signature",
        )

    payload = await request.json()

    service = FlutterwaveService(db)

    success, message = await service.handle_webhook_event(payload)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        )

    return {
        "status": "success",
        "detail": message,
    }