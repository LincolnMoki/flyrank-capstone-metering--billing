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
    
    
