from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.entities import Tenant

router = APIRouter()


@router.get("")
async def get_tenant_usage(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Fetch tenant details and usage metrics from PostgreSQL using AsyncSession."""
    result = await db.execute(select(Tenant).where(Tenant.api_key == x_api_key))
    tenant = result.scalar_one_or_none()

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

    return {
        "status": "success",
        "tenant": {
            "id": str(tenant.id),
            "name": tenant.name,
            "is_active": tenant.is_active,
        },
        "usage": {
            "total_requests": 0,
            "tokens_consumed": 0,
            "current_period_cost": 0.00,
        },
    }