from fastapi import APIRouter, Depends, Header, HTTPException, status, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from typing import Any, Optional
from fastapi.security import APIKeyHeader
from app.db.session import get_db
from app.models.entities import Tenant, UsageEvent
from app.services.pricing import calculate_usage_cost
from app.services.billing import BillingService

router = APIRouter()

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=True,
)

@router.post("/snapshot/{tenant_id}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_snapshot(tenant_id: str, request: Request):
    """Enqueue background processing without blocking the response."""
    job = await request.app.state.arq_pool.enqueue_job(
        "process_usage_snapshot",
        tenant_id,
    )
    return {
        "status": "queued",
        "job_id": job.job_id,
        "message": "Background usage snapshot enqueued successfully.",
    }
class UsageEventCreate(BaseModel):
    idempotency_key: str = Field(..., max_length=255)
    usage_type: str = Field(default="ai_tokens", max_length=50)
    standard_input_tokens: int = Field(default=0, ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    reasoning_tokens: int = Field(default=0, ge=0)
    metadata_json: Optional[dict[str, Any]] = Field(default=None)

@router.post("", status_code=status.HTTP_201_CREATED)

@router.post("", status_code=status.HTTP_201_CREATED)
async def ingest_usage_event(
    payload: UsageEventCreate,
    request: Request,
    x_api_key: str = Depends(api_key_header),
    db: AsyncSession = Depends(get_db),
):
    """Ingest a usage event through the centralized billing service."""

    tenant_result = await db.execute(
        select(Tenant).where(Tenant.api_key == x_api_key)
    )
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

    redis = request.app.state.redis

    service = BillingService(
        db=db,
        redis=redis,
    )

    success, status_code, message = await service.record_usage(
        tenant_id=tenant.id,
        idempotency_key=payload.idempotency_key,
        standard_input_tokens=payload.standard_input_tokens,
        cached_input_tokens=payload.cached_input_tokens,
        output_tokens=payload.output_tokens,
        reasoning_tokens=payload.reasoning_tokens,
    )

    if not success:
        raise HTTPException(
            status_code=status_code,
            detail=message,
        )

    return {
        "status": "success",
        "message": message,
        "tenant_id": str(tenant.id),
        "idempotency_key": payload.idempotency_key,
        "status_code": status_code,
    }

@router.get("")
async def get_tenant_usage(
    x_api_key: str = Depends(api_key_header),
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