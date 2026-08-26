import uuid
from datetime import datetime, timezone
from typing import Tuple, Optional

import redis.asyncio as aioredis
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Tenant, UsageEvent
from app.core.config import calculate_cost_microcents


class BillingService:
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
        Processes a usage event with strict idempotency and
        monthly quota enforcement.

        Returns:
            (success, HTTP status code, detail message)
        """

        # Calculate total tokens if not explicitly supplied.
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

        # Idempotency check — prevents double counting.
        dedup_key = f"idempotency:{tenant_id}:{idempotency_key}"
        is_new = await self.redis.set(
            dedup_key,
            "1",
            nx=True,
            ex=86400,  # 24 hours
        )

        if not is_new:
            return True, 200, "Duplicated event ignored"

        # Fetch tenant.
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await self.db.execute(stmt)
        tenant = result.scalar_one_or_none()

        if not tenant:
            return False, 404, "Tenant not found"

        # Current UTC calendar month.
        first_of_month = datetime.now(timezone.utc).replace(
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )

        # Aggregate ONLY usage from the current month.
        usage_stmt = (
            select(
                func.coalesce(
                    func.sum(UsageEvent.total_tokens),
                    0,
                )
            )
            .where(
                UsageEvent.tenant_id == tenant_id,
                UsageEvent.created_at >= first_of_month,
            )
        )

        usage_res = await self.db.execute(usage_stmt)
        current_tokens = usage_res.scalar() or 0

        # Enforce monthly quota.
        quota_limit = getattr(tenant, "token_quota", 100_000)

        if current_tokens + total_tokens > quota_limit:
            return False, 402, "Quota Exceeded: Payment Required"

        # Calculate cost in integer micro-cents.
        cost_microcents = calculate_cost_microcents(
            standard_input_tokens=standard_input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
        )

        # Record usage event.
        event = UsageEvent(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            standard_input_tokens=standard_input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            cost_microcents=cost_microcents,
        )

        self.db.add(event)
        await self.db.commit()

        return True, 201, "Usage Recorded Successfully"