import uuid
from typing import Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.entities import Tenant, Subscription, UsageEvent
from app.core.config import calculate_cost_microcents
import redis.asyncio as aioredis

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
        Processes usage event with strict idempotency and HTTP 402 quota enforcement checks.
        Returns: (success_flags, https_status_code, detail_message)
        """
        # calculating tokens if not explicitly passed
        total_tokens = (
            tokens_used
            if tokens_used is not None
            else (standard_input_tokens + cached_input_tokens + output_tokens + reasoning_tokens)
        )

        # Idempotency Check (Prevent Double-Counting)
        dedup_key = f"idempotency:{tenant_id}:{idempotency_key}"
        is_new = await self.redis.set(dedup_key, "1", nx=True, ex=86400)# 24h expiration
        if not is_new:
            return True, 200, "Duplicated event ignored"
        
        # fetch tenant & subscriptionimport uuid
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await self.db.execute(stmt)
        tenant = result.scalar_one_or_none()
        if not tenant:
            return False, 404, "Tenant not found"
        
        # Quota Enforcement Check
        # Aggregate monthly usage tokens
        usage_stmt = select(func.coalesce(func.sum(UsageEvent.total_tokens), 0)).where( 
            UsageEvent.tenant_id == tenant_id
        )
        usage_res = await self.db.execute(usage_stmt)
        current_tokens = usage_res.scalar() or 0

        # Enforce quota limit (402 Payment Required)
        quota_limit = getattr(tenant, "token_quota", 100_000)
        if current_tokens + tokens_used > quota_limit:
            return False, 402, "Quota Exceeded: Payment Required"

        # compute micro-cent Cost
        cost_microcents = calculate_cost_microcents(
            standard_input_tokens=standard_input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
        )
        
        # record Usage Event
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
        



        