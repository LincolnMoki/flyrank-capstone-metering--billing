import uuid
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.entities import Tenant, UsageEvent

class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_usage_rollup(
        self,
        tenant_id = uuid.UUID,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Aggregates AI token consumption across token type and calculates total cost rollups in micro-cents and USD for a given tenant.
        """
        # Fetch tenant details
        tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
        tenant_res = await self.db.execute(tenant_stmt)
        tenant = tenant_res.scalar_one_or_none()
        if not tenant:
            return {"error": "Tenant not found"}

        # Build aggregation query
        query = select(
            func.coalesce(func.sum(UsageEvent.standard_input_tokens), 0).label("standard_input")
            func.coalesce(func.sum(UsageEvent.cached_input_tokens), 0).label("cached_input"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output"),
            func.coalesce(func.sum(UsageEvent.reasoning_tokens), 0).label("reasoning"),
            func.coalesce(func.sum(UsageEvent.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(UsageEvent.cost_microcents), 0).label("total_microcents"),
            func.count(UsageEvent.id).label("total_events"),
        ).where(UsageEvent.tenant_id == tenant_id)

        if start_date:
            query = query.where(UsageEvent.created_at >= start_date)
        if end_date:
            query = query.where(UsageEvent.created_at <= end_date)

        res = await self.db.execute(query)
        row = res.one()

        total_microcents = int(row.total_microcents)
        cost_usd = round(total_microcents / 1_000_000, 6)

        return {
            "tenant_id": str(tenant_id),
            "plan": getattr(tenant, "plan", "free"),
            "token_quota": getattr(tenant, "token_quota", 100_000),
            "token_breakdown": {
                "standard_input_tokens": int(row.standard_input),
                "cached_input_tokens": int(row.cached_input),
                "output_tokens": int(row.output),
                "reasoning_tokens": int(row.reasoning),
                "total_tokens": int(row.total_tokens),
            },
            "cost_summary": {
                "total_cost_microcents": total_microcents,
                "total_cost_usd": cost_usd,
            },
            "total_events": int(row.total_events),
        }
    