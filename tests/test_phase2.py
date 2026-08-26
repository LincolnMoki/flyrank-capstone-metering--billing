import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from app.services.billing import BillingService

@pytest.mark.asyncio
async def test_double_count_prevention():
    """
    Verify  duplicate idempotency keys return 200 without re-recording usage
    """
    db = AsyncMock()
    db.add = MagicMock()
    redis = AsyncMock()
    # simulate existing keys
    redis.set.return_value = False
    service = BillingService(db,redis)
    tenant_id = uuid.uuid4()
    success, status_code, msg = await service.record_usage(tenant_id, "evt_123", 500)
    assert success is True
    assert status_code == 200
    assert msg == "Duplicated event ignored"
    db.add.assert_not_called()

@pytest.mark.asyncio
async def test_quota_exceeded_returns_402():
    """
    Verify usage exceeding quota returns HTTP 402 Payment Required.
    """
    db=AsyncMock()
    db.add = MagicMock()
    redis=AsyncMock()
    redis.set.return_value = True

    # Mock tenant with quota of 1000 tokens
    mock_tenant = MagicMock()
    mock_tenant.token_quota = 1000

    db_result_tenant = MagicMock()
    db_result_tenant.scalar_one_or_none.return_value = mock_tenant

    db_result_usage = MagicMock()
    db_result_usage.scalar.return_value = 900 # Current usage is 900

    db.execute.side_effect = [db_result_tenant, db_result_usage]

    service = BillingService(db, redis)
    tenant_id = uuid.uuid4()
    # request 200 tokens (900 + 200 = 1100 > 1000 quota)
    success, status_code, msg = await service.record_usage(tenant_id, "evt_124", 200)

    assert success is False
    assert status_code == 402
    assert "quota exceeded" in msg.lower()

@pytest.mark.asyncio
async def test_quota_uses_current_month_only():
    """
    Verify quota enforcement uses only current-month usage.

    Scenario:
        Previous month: 80,000 tokens
        Current month:  30,000 tokens
        Monthly quota: 100,000 tokens
        New request:    10,000 tokens

    Expected:
        Current-month usage = 30,000
        30,000 + 10,000 = 40,000
        Request is accepted with HTTP 201.

    The previous month's 80,000 tokens must not affect the quota check.
    """
    db = AsyncMock()
    db.add = MagicMock()
    redis = AsyncMock()
    redis.set.return_value = True

    # Mock tenant with a 100,000 token monthly quota.
    mock_tenant = MagicMock()
    mock_tenant.token_quota = 100_000

    # First database call: fetch tenant.
    db_result_tenant = MagicMock()
    db_result_tenant.scalar_one_or_none.return_value = mock_tenant

    # Second database call: current-month usage.
    # Previous month's 80,000 tokens are intentionally excluded.
    db_result_usage = MagicMock()
    db_result_usage.scalar.return_value = 30_000

    db.execute.side_effect = [
        db_result_tenant,
        db_result_usage,
    ]

    service = BillingService(db, redis)
    tenant_id = uuid.uuid4()

    # Current month = 30,000
    # New request = 10,000
    # Total = 40,000
    # Quota = 100,000
    success, status_code, msg = await service.record_usage(
        tenant_id,
        "evt_month_boundary",
        standard_input_tokens=10_000,
    )

    assert success is True
    assert status_code == 201
    assert msg == "Usage Recorded Successfully"

    # Verify both database operations occurred:
    # 1. Fetch tenant
    # 2. Aggregate current-month usage
    assert db.execute.call_count == 2

    # Inspect the usage aggregation query.
    usage_query = db.execute.call_args_list[1].args[0]
    query_text = str(usage_query)

    # The quota query must contain the monthly created_at filter.
    assert "created_at" in query_text  
