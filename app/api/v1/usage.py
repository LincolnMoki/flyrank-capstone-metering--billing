from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.db.session import get_db
from app.models.entities import Tenant, UsageEvent

router = APIRouter()


@router.get("")
async def get_tenant_usage(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Fetch tenant details and usage metrics from PostgreSQL using AsyncSession."""
    tenant_result = await db.execute(select(Tenant).where(Tenant.api_key == x_api_key))
    tenant = tenant_result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found for provided API key",
        )

    if not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant account is inactive",
        )
    
    # Window usage to the current calendar month (UTC)
    first_of_month = datetime.now(timezone.utc).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )

    # Aggregate total requests, token sum, and total cost
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
    usage_metrics = usage_result.one()

    # Convert microcents to standard USD float (1 USD = 100,000,000 microcents)
    cost_usd = round(float(usage_metrics.total_microcents) / 100_000_000.0, 6)

    return {
        "status": "success",
        "tenant": {
            "id": str(tenant.id),
            "name": tenant.name,
            "is_active": tenant.is_active,
        },
        "usage": {
            "total_requests": usage_metrics.total_requests,
            "tokens_consumed": usage_metrics.tokens_consumed,
            "current_period_cost": cost_usd,
        },
    }