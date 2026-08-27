import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import Tenant, Subscription, WebhookLog


class FlutterwaveService:
    BASE_URL = "https://api.flutterwave.com/v3"

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_checkout_session(
        self,
        tenant_id: uuid.UUID,
        plan_id: str,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, str]:

        tenant_result = await self.db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = tenant_result.scalar_one_or_none()

        if not tenant:
            raise ValueError("Tenant not found")

        if plan_id.lower() != "pro":
            raise ValueError("Unsupported plan")

        tx_ref = f"flyrank-pro-{tenant_id}-{uuid.uuid4()}"

        payload = {
            "tx_ref": tx_ref,
            "amount": 10,
            "currency": "USD",
            "redirect_url": success_url,
            "customer": {
                "email": f"{tenant_id}@flyrank.demo",
                "name": tenant.name,
            },
            "customizations": {
                "title": "FlyRank Pro",
                "description": "FlyRank Pro subscription",
            },
            "meta": {
                "tenant_id": str(tenant_id),
                "plan_id": "pro",
                "cancel_url": cancel_url,
            },
        }

        headers = {
            "Authorization": f"Bearer {settings.FLW_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.BASE_URL}/payments",
                json=payload,
                headers=headers,
            )

        response.raise_for_status()

        data = response.json()

        if data.get("status") != "success":
            raise ValueError(
                data.get("message", "Flutterwave checkout failed")
            )

        return {
            "session_id": tx_ref,
            "checkout_url": data["data"]["link"],
        }

    async def handle_webhook_event(
        self,
        event: dict[str, Any],
    ) -> tuple[bool, str]:

        event_id = event.get("id")

        if not event_id:
            return False, "Missing webhook event ID"

        # Idempotency check
        existing_result = await self.db.execute(
            select(WebhookLog).where(
                WebhookLog.stripe_event_id == event_id
            )
        )

        if existing_result.scalar_one_or_none():
            return True, "Duplicate webhook event ignored"

        event_type = event.get("type", "")
        data = event.get("data", {})

        # Record webhook
        webhook_log = WebhookLog(
            stripe_event_id=event_id,
            event_type=event_type,
            payload=event,
        )

        self.db.add(webhook_log)

        if event_type != "charge.completed":
            await self.db.commit()
            return True, "Webhook received"

        if data.get("status") != "successful":
            await self.db.commit()
            return True, "Payment not successful"

        meta = data.get("meta", {})
        tenant_id = meta.get("tenant_id")
        plan_id = meta.get("plan_id")

        if not tenant_id:
            await self.db.commit()
            return False, "Missing tenant_id"

        if plan_id != "pro":
            await self.db.commit()
            return False, "Unsupported plan"

        tenant_result = await self.db.execute(
            select(Tenant).where(
                Tenant.id == uuid.UUID(tenant_id)
            )
        )

        tenant = tenant_result.scalar_one_or_none()

        if not tenant:
            await self.db.commit()
            return False, "Tenant not found"

        # Upgrade tenant
        tenant.plan = "pro"
        tenant.token_quota = 10_000_000

        subscription_result = await self.db.execute(
            select(Subscription).where(
                Subscription.tenant_id == tenant.id
            )
        )

        subscription = subscription_result.scalar_one_or_none()

        if subscription:
            subscription.plan_tier = "pro"
            subscription.status = "active"
            subscription.api_token_quota = 10_000_000
        else:
            subscription = Subscription(
                tenant_id=tenant.id,
                plan_tier="pro",
                status="active",
                api_token_quota=10_000_000,
                api_call_quota=10000,
                stripe_customer_id=None,
                stripe_subscription_id=None,
            )

            self.db.add(subscription)

        await self.db.commit()

        return True, "Webhook processed successfully"