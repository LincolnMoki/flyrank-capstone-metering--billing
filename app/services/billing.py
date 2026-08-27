import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import calculate_cost_microcents
from app.models.entities import Subscription, Tenant, UsageEvent


class BillingService:
    """
    Centralized usage metering and quota enforcement service.

    Responsibilities:
    - Idempotent usage recording
    - Monthly API-call quota enforcement
    - Monthly AI-token quota enforcement
    - Usage cost calculation
    - Persistent usage-event recording
    """

    IDEMPOTENCY_TTL = 86400  # 24 hours

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def record_usage(
        self,
        tenant_id: uuid.UUID,
        idempotency_key: str,
        standard_input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        tokens_used: Optional[int] = None,
    ) -> Tuple[bool, int, str]:
        """
        Record one usage event after enforcing the tenant's monthly quotas.

        Quotas enforced:
        - API calls: number of UsageEvent records in the current month
        - AI tokens: sum of UsageEvent.total_tokens in the current month

        Returns:
            (success, HTTP status code, detail message)
        """

        # ---------------------------------------------------------
        # 1. Calculate total tokens
        # ---------------------------------------------------------
        total_tokens = (
            tokens_used
            if tokens_used is not None
            else (
                standard_input_tokens
                + cached_input_tokens
                + output_tokens
                + reasoning_tokens
            )
        )

        # Defensive validation for callers that bypass Pydantic.
        if total_tokens < 0:
            return False, 422, "Token usage cannot be negative"

        # ---------------------------------------------------------
        # 2. Idempotency check
        # ---------------------------------------------------------
        dedup_key = f"idempotency:{tenant_id}:{idempotency_key}"

        is_new = await self.redis.set(
            dedup_key,
            "1",
            nx=True,
            ex=self.IDEMPOTENCY_TTL,
        )

        if not is_new:
            return True, 200, "Duplicated event ignored"

        # ---------------------------------------------------------
        # 3. Fetch tenant
        # ---------------------------------------------------------
        tenant_result = await self.db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )

        tenant = tenant_result.scalar_one_or_none()

        if not tenant:
            # Do not leave an idempotency key behind for a failed request.
            await self.redis.delete(dedup_key)

            return False, 404, "Tenant not found"

        if not tenant.is_active:
            await self.redis.delete(dedup_key)

            return False, 403, "Tenant account is inactive"

        # ---------------------------------------------------------
        # 4. Fetch subscription
        # ---------------------------------------------------------
        subscription_result = await self.db.execute(
            select(Subscription).where(
                Subscription.tenant_id == tenant_id
            )
        )

        subscription = subscription_result.scalar_one_or_none()

        if not subscription:
            await self.redis.delete(dedup_key)

            return False, 402, "Active subscription required"

        # ---------------------------------------------------------
        # 5. Verify subscription status
        # ---------------------------------------------------------
        if subscription.status.lower() not in {
            "active",
            "trialing",
        }:
            await self.redis.delete(dedup_key)

            return False, 402, "Active subscription required"

        # ---------------------------------------------------------
        # 6. Determine current UTC month
        # ---------------------------------------------------------
        first_of_month = datetime.now(timezone.utc).replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        # ---------------------------------------------------------
        # 7. Aggregate current-month usage
        #
        # API calls = number of usage events
        # AI tokens = sum of total_tokens
        # ---------------------------------------------------------
        usage_stmt = (
            select(
                func.count(UsageEvent.id).label("api_calls"),
                func.coalesce(
                    func.sum(UsageEvent.total_tokens),
                    0,
                ).label("tokens"),
            )
            .where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.created_at >= first_of_month,
            )
        )

        usage_result = await self.db.execute(usage_stmt)
        usage_metrics = usage_result.one()

        current_api_calls = int(usage_metrics.api_calls or 0)
        current_tokens = int(usage_metrics.tokens or 0)

        # ---------------------------------------------------------
        # 8. Read quotas from Subscription
        # ---------------------------------------------------------
        api_call_quota = subscription.api_call_quota
        api_token_quota = subscription.api_token_quota

        # ---------------------------------------------------------
        # 9. Enforce API-call quota
        # ---------------------------------------------------------
        if current_api_calls + 1 > api_call_quota:
            await self.redis.delete(dedup_key)

            return False, 402, "Quota Exceeded: Payment Required"

        # ---------------------------------------------------------
        # 10. Enforce AI-token quota
        # ---------------------------------------------------------
        if current_tokens + total_tokens > api_token_quota:
            await self.redis.delete(dedup_key)

            return False, 402, "Quota Exceeded: Payment Required"

        # ---------------------------------------------------------
        # 11. Calculate usage cost
        # ---------------------------------------------------------
        cost_microcents = calculate_cost_microcents(
            standard_input_tokens=standard_input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
        )

        # ---------------------------------------------------------
        # 12. Create usage event
        # ---------------------------------------------------------
        event = UsageEvent(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            usage_type="ai_tokens",
            standard_input_tokens=standard_input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            cost_microcents=cost_microcents,
            metadata_json={},
        )

        self.db.add(event)

        # ---------------------------------------------------------
        # 13. Persist usage event
        # ---------------------------------------------------------
        try:
            await self.db.commit()
        except Exception:
            # The database write failed, so allow the same idempotency
            # key to be retried.
            await self.redis.delete(dedup_key)
            raise

        return True, 201, "Usage Recorded Successfully"