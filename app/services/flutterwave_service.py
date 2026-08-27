import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.entities import Tenant, Subscription, WebhookLog


class FlutterwaveService:
    """
    Flutterwave billing integration.

    Uses Flutterwave's OAuth 2.0 API and v4 sandbox endpoints.
    The sandbox checkout flow is:

        OAuth token -> customer -> checkout session

    Payment truth remains with Flutterwave; the local database is
    synchronized through verified webhook events.
    """

    TOKEN_URL = (
        "https://idp.flutterwave.com/realms/flutterwave/"
        "protocol/openid-connect/token"
    )
    BASE_URL = "https://developersandbox-api.flutterwave.com"

    PLAN_QUOTAS = {
        "free": 100_000,
        "pro": 10_000_000,
        "enterprise": 100_000_000,
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self._access_token: str | None = None
        self._access_token_expires_at: float = 0.0

    async def _get_access_token(self) -> str:
        """
        Retrieve a short-lived OAuth access token.

        Flutterwave OAuth tokens are valid for approximately 10 minutes.
        Refresh one minute before expiry.
        """
        import time

        now = time.time()

        if (
            self._access_token
            and now < self._access_token_expires_at - 60
        ):
            return self._access_token

        if not settings.FLW_CLIENT_ID or not settings.FLW_CLIENT_SECRET:
            raise ValueError(
                "Flutterwave OAuth credentials are not configured"
            )

        payload = {
            "client_id": settings.FLW_CLIENT_ID,
            "client_secret": settings.FLW_CLIENT_SECRET,
            "grant_type": "client_credentials",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.TOKEN_URL,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )

        if response.is_error:
            raise ValueError(
                f"Flutterwave checkout error "
                f"{response.status_code}: {response.text}"
            )

        data = response.json()
        access_token = data.get("access_token")
        expires_in = int(data.get("expires_in", 600))

        if not access_token:
            raise ValueError("Flutterwave OAuth response missing access_token")

        self._access_token = access_token
        self._access_token_expires_at = now + expires_in

        return access_token

    async def _create_customer(
        self,
        tenant: Tenant,
        access_token: str,
    ) -> str:
        """
        Create a Flutterwave v4 customer for the tenant.
        """
        payload = {
            "name": tenant.name,
            "email": f"{tenant.id}@flyrank.demo",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.BASE_URL}/customers",
                json=payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "X-Trace-Id": str(uuid.uuid4()),
                    "X-Idempotency-Key": str(uuid.uuid4()),
                },
            )

        if response.is_error:
            raise ValueError(
                f"Flutterwave checkout error "
                f"{response.status_code}: {response.text}"
            )

        data = response.json()

        if data.get("status") != "success":
            raise ValueError(
                data.get("message", "Flutterwave customer creation failed")
            )

        customer_id = data.get("data", {}).get("id")

        if not customer_id:
            raise ValueError(
                "Flutterwave customer response missing customer id"
            )

        return str(customer_id)

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

        plan_id = plan_id.lower()

        if plan_id != "pro":
            raise ValueError("Unsupported plan")

        subscription_result = await self.db.execute(
            select(Subscription).where(
                Subscription.tenant_id == tenant_id
            )
        )
        subscription = subscription_result.scalar_one_or_none()

        access_token = await self._get_access_token()

        customer_id = (
            str(subscription.flutterwave_customer_id)
            if subscription
            and subscription.flutterwave_customer_id
            else None
        )

        if not customer_id:
            customer_id = await self._create_customer(
                tenant=tenant,
                access_token=access_token,
            )

            if subscription:
                subscription.flutterwave_customer_id = customer_id
                await self.db.commit()

        reference = f"flyrank-pro-{uuid.uuid4().hex[:20]}"

        payload = {
            "amount": 10,
            "currency": "USD",
            "customer_id": customer_id,
            "redirect_url": success_url,
            "reference": reference,
            "max_retry_attempts": 3,
            "session_duration": 30,
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Trace-Id": str(uuid.uuid4()),
            "X-Idempotency-Key": str(uuid.uuid4()),
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.BASE_URL}/checkout/sessions",
                json=payload,
                headers=headers,
            )

        if response.is_error:
            raise ValueError(
                f"Flutterwave checkout error "
                f"{response.status_code}: {response.text}"
            )

        data = response.json()

        if data.get("status") != "success":
            raise ValueError(
                data.get("message", "Flutterwave checkout failed")
            )

        checkout_data = data.get("data", {})

        session_id = checkout_data.get("id")
        provider_redirect_url = checkout_data.get("redirect_url")

        if not session_id:
            raise ValueError(
                "Flutterwave checkout response missing session id"
            )

        if not provider_redirect_url:
            raise ValueError(
                "Flutterwave checkout response missing redirect URL"
            )

        return {
            "session_id": str(session_id),
            "checkout_url": str(provider_redirect_url),
        }


    async def handle_webhook_event(
        self,
        event: dict[str, Any],
    ) -> tuple[bool, str]:

        event_id = event.get("id") or event.get("webhook_id")

        if not event_id:
            return False, "Missing webhook event ID"

        # Idempotency check
        existing_result = await self.db.execute(
            select(WebhookLog).where(
                WebhookLog.flutterwave_event_id == str(event_id)
            )
        )

        if existing_result.scalar_one_or_none():
            return True, "Duplicate webhook event ignored"

        event_type = event.get("type", "")
        data = event.get("data", {})

        # Record webhook
        webhook_log = WebhookLog(
            flutterwave_event_id=str(event_id),
            event_type=event_type,
            payload=event,
        )

        self.db.add(webhook_log)

        # Flutterwave v4 emits charge.completed for completed payments.
        if event_type != "charge.completed":
            await self.db.commit()
            return True, "Webhook received"

        # v4 successful charges use "succeeded".
        if data.get("status") not in {"successful", "succeeded"}:
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

        try:
            tenant_uuid = uuid.UUID(str(tenant_id))
        except ValueError:
            await self.db.commit()
            return False, f"Invalid tenant_id format: {tenant_id}"

        tenant_result = await self.db.execute(
            select(Tenant).where(Tenant.id == tenant_uuid)
        )

        tenant = tenant_result.scalar_one_or_none()

        if not tenant:
            await self.db.commit()
            return False, "Tenant not found"

        subscription_result = await self.db.execute(
            select(Subscription).where(
                Subscription.tenant_id == tenant.id
            )
        )

        subscription = subscription_result.scalar_one_or_none()

        quota = self.PLAN_QUOTAS["pro"]

        if subscription:
            subscription.plan_tier = "pro"
            subscription.status = "active"
            subscription.api_token_quota = quota
            subscription.api_call_quota = 10_000

        else:
            subscription = Subscription(
                tenant_id=tenant.id,
                plan_tier="pro",
                status="active",
                api_token_quota=quota,
                api_call_quota=10_000,
                flutterwave_customer_id=None,
                flutterwave_transaction_id=str(
                    data.get("id") or event_id
                ),
            )

            self.db.add(subscription)

        # Save Flutterwave payment identifiers when available.
        customer = data.get("customer")

        if isinstance(customer, dict):
            customer_id = customer.get("id")
            if customer_id:
                subscription.flutterwave_customer_id = str(customer_id)
        elif customer:
            subscription.flutterwave_customer_id = str(customer)

        transaction_id = data.get("id")

        if transaction_id:
            subscription.flutterwave_transaction_id = str(
                transaction_id
            )

        await self.db.commit()

        return True, "Webhook processed successfully"

    async def cancel_subscription(
        self,
        tenant_id: uuid.UUID,
    ) -> tuple[bool, str]:

        subscription_result = await self.db.execute(
            select(Subscription).where(
                Subscription.tenant_id == tenant_id
            )
        )

        subscription = subscription_result.scalar_one_or_none()

        if not subscription:
            return False, "Subscription not found"

        subscription.plan_tier = "FREE"
        subscription.status = "canceled"
        subscription.api_token_quota = self.PLAN_QUOTAS["free"]
        subscription.api_call_quota = 1000

        await self.db.commit()

        return True, "Subscription canceled successfully"