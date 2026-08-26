import os
import uuid
from typing import Tuple, Dict, Any, Optional
import stripe
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.entities import Tenant, Subscription, WebhookLog

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_placeholder")

stripe.api_key = STRIPE_SECRET_KEY

PLAN_QUOTAS = {
    "free":100_000,
    "pro": 10_000_000,
    "enterprise": 100_000_000,
}


class StripeService:
    def __init__ (self, db: AsyncSession):
        self.db = db

    async def create_checkout_session(
            self, tenant_id: uuid.UUID, plan_id: str, success_url: str, cancel_url: str
    ) -> Dict[str, Any]:
        """
        Create a Stripe Checkout Session for plan upgrades.
        """
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            client_reference_id=str(tenant_id),
            metadata={"tenant_id": str(tenant_id), "plan_id": plan_id},
            line_items=[
                {
                    "price_data":{
                        "currency":"usd",
                        "product_data":{
                            "name": f"FlyRank AI {plan_id.capitalize()} Plan",
                        },
                        "unit_amount": 4900 if plan_id == "pro" else 19900,
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }
            ],
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return { 
            "session_id": session.id,
            "checkout_url": session.url
        }

    def verify_webhook_signature(
            self, payload: bytes | str, sig_header: str, webhook_secret: Optional[str] = None
    ) -> stripe.Event:
        """
        Verify Event Signature header against event payload.
        """
        secret = webhook_secret or STRIPE_WEBHOOK_SECRET
        return stripe.Webhook.construct_event(payload, sig_header, secret)
    
    async def handle_webhook_event(self, event: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Processes webhooks with strict deduplication using WebhookLog.
        Flips tenant plan from Free -> Pro upon checkout completion.
        """
        event_id = event.get("id")
        event_type = event.get("type")
        data_object = event.get("data", {}).get("object", {})

        if not event_id or not event_type:
            return False, "Invalid event Payload missing id or type"

        # Deduplication check via WebhookLog
        stmt = select(WebhookLog).where(WebhookLog.stripe_event_id == event_id)
        res = await self.db.execute(stmt)
        existing_log = res.scalar_one_or_none()
        if existing_log:
            return True, "Duplicate webhook event ignored"
        
        # Handle upgrade Events
        if event_type == "checkout.session.completed":
            metadata = data_object.get("metadata", {})
            tenant_id_str = metadata.get("tenant_id") or data_object.get("client_reference_id")
            new_plan = metadata.get("plan_id", "pro")

            if tenant_id_str:
                try:
                    tenant_id = uuid.UUID(tenant_id_str)
                    await self._upgrade_tenant_plan(tenant_id, new_plan, data_object)
                except ValueError:
                    return False, f"Invalid tenant_id format: {tenant_id_str}"

        elif event_type in ("customer.subscription.updated", "customer.subscription.update"):
            metadata = data_object.get("metadata", {})
            tenant_id_str = metadata.get("tenant_id")
            new_plan = metadata.get("plan_id", "pro")
            status = metadata.get("status")

            if tenant_id_str and status == "active":
                try:
                    tenant_id = uuid.UUID(tenant_id_str)
                    await self._upgrade_tenant_plan(tenant_id, new_plan, data_object)
                except ValueError:
                    return False, f"Invalid tenant_id format: {tenant_id_str}"

        elif event_type == "customer.subscription.deleted":
            metadata = data_object.get("metadata", {})
            tenant_id_str = metadata.get("tenant_id")

            if tenant_id_str:
                try:
                    tenant_id = uuid.UUID(tenant_id_str)

                    tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
                    tenant_res = await self.db.execute(tenant_stmt)
                    tenant = tenant_res.scalar_one_or_none()

                    if tenant:
                        # Return tenant to Free plan
                        tenant.plan = "free"
                        tenant.token_quota = PLAN_QUOTAS["free"]

                        # Mark subscription as canceled
                        sub_stmt = select(Subscription).where(
                            Subscription.tenant_id == tenant_id
                        )
                        sub_res = await self.db.execute(sub_stmt)
                        subscription = sub_res.scalar_one_or_none()

                        if subscription:
                            subscription.plan_tier = "free"
                            subscription.status = "canceled"
                            subscription.api_token_quota = PLAN_QUOTAS["free"]

                except ValueError:
                    return False, f"Invalid tenant_id format: {tenant_id_str}"


        # log events as processed
        log = WebhookLog(
            stripe_event_id=event_id,
            event_type=event_type,
            payload=event,
        )
        self.db.add(log)
        await self.db.commit()

        return True, "Webhook processed successfully"

    async def _upgrade_tenant_plan(
        self, tenant_id: uuid.UUID, new_plan: str, stripe_data: Dict[str, Any]
    ) ->None:
        """
        Updates Tenant Plan and Quota & syncs subscription record.
        """
        tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
        tenant_res = await self.db.execute(tenant_stmt)
        tenant = tenant_res.scalar_one_or_none()

        if not tenant:
            return

        quota = PLAN_QUOTAS.get(new_plan.lower(), 100_000)
        
        tenant.plan = new_plan
        tenant.token_quota = quota

        sub_stmt = select(Subscription).where(Subscription.tenant_id == tenant_id)
        sub_res = await self.db.execute(sub_stmt)
        subscription = sub_res.scalar_one_or_none()

        stripe_sub_id = stripe_data.get("subscription") or stripe_data.get("id")
        stripe_cust_id = stripe_data.get("customer")

        if subscription:
            subscription.plan_tier  = new_plan
            subscription.status = "active"
            subscription.api_token_quota = quota
            if stripe_sub_id:
                subscription.stripe_subscription_id =  str(stripe_sub_id)
            if stripe_cust_id:
                subscription.stripe_customer_id = str(stripe_cust_id)

        else:
            subscription = Subscription(
                tenant_id=tenant_id,
                plan_tier=new_plan,
                status="active",
                stripe_subscription_id=str(stripe_sub_id) if stripe_sub_id else None,
                stripe_customer_id=str(stripe_cust_id) if stripe_cust_id else None,
                api_token_quota=quota,
            )
            self.db.add(subscription)
        