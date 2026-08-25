import uuid
from typing import Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.entities import Tenant, Subscription, UsageEvent
import redis.asyncio as aioredis

class BillingService:
    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    async def record_usage(
            self, tenant_id: uuid.UUID, idempotency_key: str, tokens_used: int
    ) -> Tuple[bool, int, str]:
        """
        Processes usage event with strict idempotency and quota checks.
        Returns: (success_flags, https_status_code, detail_message)
        """
        # Idempotency Check (Prevent Double-Counting)
        dedup_key = f"idempotency:{tenant_id}:{idempotency_key}"
        is_new = await self.redis.set(dedup_key, "1", nx=True, ex=86400)# 24h expiration
        if not is_new:
            return True, 200, "Duplicated event ignored"
        # fetch tenant & subscription
        stmt = select(Tenant).where(Tenant.id == tenant_id)
        result = await self.db.execute(stmt)
        tenant = result.scalar_one_or_none()
        if not tenant:
            return False, 404, "Tenant not found"
        # Quota Enforcement Check
        # Aggregate monthly usage tokens
        usage_stmt = select(func.sum(UsageEvent.total_tokens)).where( UsageEvent.tenant_id == tenant_id)
        usage_res = await self.db.execute(usage_stmt)
        current_tokens = usage_res.scalar() or 0
        # Enforce quota limit (402 Payment Required)
        if current_tokens + tokens_used > tenant.token.quota:
            return False, 402, "Quota Exceeded: Payment Required"
        # record Usage Event
        event = UsageEvent(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            total_tokens=tokens_used,
        )
        self.db.add(event)
        await self.db.commit()
        return True, 201, "Usage Recorded Successfully"
