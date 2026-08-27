import uuid
from typing import Optional, Any

from app.core.config import settings
from fastapi import APIRouter, Depends, HTTPException, Request, Header, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.flutterwave_service import FlutterwaveService
from app.db.session import get_db
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from app.models.entities import Tenant

router = APIRouter()

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)
class CheckoutRequest(BaseModel):
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
    x_api_key: str = Depends(api_key_header),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a Flutterwave hosted payment session.
    """
    tenant_result = await db.execute(select(Tenant).where(Tenant.api_key == x_api_key))
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found for provided API key")
    if not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant account is inactive")

    service = FlutterwaveService(db)

    try:
        return await service.create_checkout_session(
            tenant_id=tenant.id,
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
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "example": {
                        "id": "flw_demo_upgrade_001",
                        "type": "charge.completed",
                        "data": {
                            "id": "flw_tx_demo_001",
                            "status": "successful",
                            "amount": 10,
                            "currency": "USD",
                            "customer": {
                                "id": "flw_customer_demo_001",
                                "email": "demo@flyrank.test",
                            },
                            "meta": {
                                "tenant_id": "00000000-0000-0000-0000-000000000001",
                                "plan_id": "pro",
                            },
                        },
                    }
                }
            },
        }
    },
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
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Flutterwave webhook signature",
        )

    if verif_hash != settings.FLW_SECRET_HASH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
