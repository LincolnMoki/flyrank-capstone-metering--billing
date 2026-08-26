import logging
from typing import Any
from arq import create_pool
from arq.connections import RedisSettings
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.entities import Tenant, UsageEvent, Subscription
from sqlalchemy import select, func
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Define Redis Settings for ARQ
REDIS_SETTINGS = RedisSettings(
    host=getattr(settings, "REDIS_HOST", "localhost"),
    port=int(getattr(settings, "REDIS_PORT", 6379)),
)

async def sample_background_task(ctx, event_id: str):
    """ background worker task for processing deferred telemetry or webhook syncs."""
    logger.info(f"Processing background job for event ID: {event_id}")
    return f"Processed {event_id}"

async def process_usage_snapshot(ctx, tenant_id: str):
    """Background task to process tenant usage snapshots asynchronously."""
    logger.info(f"Processing usage snapshot for tenant: {tenant_id}")
    async with AsyncSessionLocal() as db:
        try:
            # 1. Fetch Tenant and Subscription details
            tenant_result = await db.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            tenant = tenant_result.scalar_one_or_none()
            if not tenant:
                logger.warning(f"Tenant {tenant_id} not found during snapshot processing.")
                return {"status": "error", "message": "Tenant not found"}

            # 2. Window usage to the current calendar month (UTC)
            first_of_month = datetime.now(timezone.utc).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )

            # 3. Aggregate total requests, token sum, and total cost
            usage_stmt = (
                select(
                    func.count(UsageEvent.id).label("total_requests"),
                    func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("tokens_consumed"),
                    func.coalesce(func.sum(UsageEvent.cost_microcents), 0).label("total_microcents"),
                )
                .where(UsageEvent.tenant_id == tenant.id)
                .where(UsageEvent.created_at >= first_of_month)
            )

            usage_result = await db.execute(usage_stmt)
            metrics = usage_result.one()

            # 4. Check quota thresholds against subscription limits if necessary
            sub_result = await db.execute(
                select(Subscription).where(Subscription.tenant_id == tenant.id)
            )
            subscription = sub_result.scalar_one_or_none()
            
            quota_status = "within_limits"
            if subscription:
                if metrics.tokens_consumed > subscription.api_token_quota:
                    quota_status = "token_quota_exceeded"
                    logger.warning(f"Tenant {tenant.id} has exceeded token quota! Consumed: {metrics.tokens_consumed}, Quota: {subscription.api_token_quota}")

            logger.info(
                f"Successfully generated snapshot for Tenant {tenant.name} ({tenant.id}): "
                f"Requests={metrics.total_requests}, Tokens={metrics.tokens_consumed}, "
                f"CostMicrocents={metrics.total_microcents}, Status={quota_status}"
            )

            return {
                "status": "success",
                "tenant_id": str(tenant.id),
                "total_requests": metrics.total_requests,
                "tokens_consumed": metrics.tokens_consumed,
                "total_microcents": metrics.total_microcents,
                "quota_status": quota_status,
            }

        except Exception as e:
            logger.error(f"Failed to process usage snapshot for tenant {tenant_id}: {str(e)}", exc_info=True)
            raise

class WorkerSettings:
    functions = [sample_background_task]
    redis_settings = RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
    )
    max_jobs = 10
    job_timeout = 300
    retry_jobs = True
    max_retries = 3