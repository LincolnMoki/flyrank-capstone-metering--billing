import uuid
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.services.analytics import AnalyticsService


@pytest.mark.asyncio
async def test_usage_rollup_aggregation():
    """
    Phase 4 Gate Test: Verify token rollups and cost calculations match expected sums.
    """
    db = AsyncMock()
    tenant_id = uuid.uuid4()

    mock_tenant = MagicMock()
    mock_tenant.id = tenant_id
    mock_tenant.plan = "pro"
    mock_tenant.token_quota = 10_000_000

    db_tenant_res = MagicMock()
    db_tenant_res.scalar_one_or_none.return_value = mock_tenant

    # Mock aggregated usage row
    mock_row = MagicMock()
    mock_row.standard_input = 1000
    mock_row.cached_input = 500
    mock_row.output = 2000
    mock_row.reasoning = 300
    mock_row.total_tokens = 3800
    mock_row.total_microcents = 15200  # $0.000152 USD
    mock_row.total_events = 5

    db_usage_res = MagicMock()
    db_usage_res.one.return_value = mock_row

    db.execute.side_effect = [db_tenant_res, db_usage_res]

    service = AnalyticsService(db)
    result = await service.get_usage_rollup(tenant_id)

    assert "error" not in result
    assert result["tenant_id"] == str(tenant_id)
    assert result["plan"] == "pro"
    assert result["token_breakdown"]["total_tokens"] == 3800
    assert result["token_breakdown"]["standard_input_tokens"] == 1000
    assert result["cost_summary"]["total_cost_microcents"] == 15200
    assert result["cost_summary"]["total_cost_usd"] == 0.000152
    assert result["total_events"] == 5


@pytest.mark.asyncio
async def test_usage_rollup_tenant_not_found():
    """Verify appropriate error handling when tenant ID does not exist."""
    db = AsyncMock()
    db_tenant_res = MagicMock()
    db_tenant_res.scalar_one_or_none.return_value = None
    db.execute.return_value = db_tenant_res

    service = AnalyticsService(db)
    result = await service.get_usage_rollup(uuid.uuid4())

    assert "error" in result
    assert result["error"] == "Tenant not found"
