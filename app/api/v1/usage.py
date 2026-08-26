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
async def ingest_usage_event(
    payload: UsageEventCreate,
    x_api_key: str = Depends(api_key_header),
    db: AsyncSession = Depends(get_db),
):
    """Ingest a metered usage event with robust idempotency guarantees."""
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

    total_tokens = (
        payload.standard_input_tokens
        + payload.cached_input_tokens
        + payload.output_tokens
        + payload.reasoning_tokens
    )
    
    cost_microcents = calculate_usage_cost(
        payload.standard_input_tokens,
        payload.cached_input_tokens,
        payload.output_tokens,
        payload.reasoning_tokens,
    )

    usage_event = UsageEvent(
        tenant_id=tenant.id,
        idempotency_key=payload.idempotency_key,
        usage_type=payload.usage_type,
        standard_input_tokens=payload.standard_input_tokens,
        cached_input_tokens=payload.cached_input_tokens,
        output_tokens=payload.output_tokens,
        reasoning_tokens=payload.reasoning_tokens,
        total_tokens=total_tokens,
        cost_microcents=cost_microcents,
        metadata_json=payload.metadata_json or {},
    )

    db.add(usage_event)
    try:
        await db.commit()
        await db.refresh(usage_event)
    except IntegrityError:
        await db.rollback()
        # Idempotent retry: Return existing event or success acknowledgment
        existing_event_result = await db.execute(
            select(UsageEvent).where(
                UsageEvent.tenant_id == tenant.id,
                UsageEvent.idempotency_key == payload.idempotency_key
            )
        )
        existing = existing_event_result.scalar_one_or_none()
        if existing:
            return {
                "status": "success",
                "message": "Event already processed (idempotent duplicate)",
                "event_id": str(existing.id),
                "cost_microcents": existing.cost_microcents,
            }
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate idempotency key conflict",
        )

    return {
        "status": "success",
        "event_id": str(usage_event.id),
        "total_tokens": total_tokens,
        "cost_microcents": cost_microcents,
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