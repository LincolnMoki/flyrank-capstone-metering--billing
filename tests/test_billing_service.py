import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock
from app.services.billing import BillingService

@pytest.mark.asyncio
async def test_record_usage_success():
    # Mock AsyncSession and Redis
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_redis = AsyncMock()
    
    # Redis .set() returns True for a new key (idempotency pass)
    mock_redis.set.return_value = True

    # Mock Tenant lookup result
    mock_tenant = MagicMock()
    mock_tenant.token_quota = 100_000
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_tenant
    
    # Mock current usage sum (0 tokens used so far)
    mock_usage_result = MagicMock()
    mock_usage_result.scalar.return_value = 0

    # Configure db.execute to return tenant first, then usage sum
    mock_db.execute.side_effect = [mock_result, mock_usage_result]

    service = BillingService(mock_db, mock_redis)
    
    success, status_code, message = await service.record_usage(
        tenant_id=uuid.uuid4(),
        idempotency_key="key-123",
        standard_input_tokens=1000,
        output_tokens=500
    )

    assert success is True
    assert status_code == 201
    assert message == "Usage Recorded Successfully"
    mock_db.commit.assert_awaited_once()

@pytest.mark.asyncio
async def test_record_usage_idempotency_duplicate():
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_redis = AsyncMock()
    
    # Redis .set() returns False because key already exists
    mock_redis.set.return_value = False

    service = BillingService(mock_db, mock_redis)
    
    success, status_code, message = await service.record_usage(
        tenant_id=uuid.uuid4(),
        idempotency_key="duplicate-key-456",
        tokens_used=500
    )

    assert success is True
    assert status_code == 200
    assert message == "Duplicated event ignored"
    # Should not query database or commit if duplicate is caught early
    mock_db.commit.assert_not_awaited()

@pytest.mark.asyncio
async def test_record_usage_quota_exceeded():
    mock_db = AsyncMock()
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True

    # Mock Tenant with a low quota
    mock_tenant = MagicMock()
    mock_tenant.token_quota = 1000
    
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_tenant
    
    # Mock current usage sum already at 800 tokens
    mock_usage_result = MagicMock()
    mock_usage_result.scalar.return_value = 800

    mock_db.execute.side_effect = [mock_result, mock_usage_result]

    service = BillingService(mock_db, mock_redis)
    
    # Trying to add 500 more tokens (800 + 500 = 1300 > 1000 quota)
    success, status_code, message = await service.record_usage(
        tenant_id=uuid.uuid4(),
        idempotency_key="key-789",
        tokens_used=500
    )

    assert success is False
    assert status_code == 402
    assert message == "Quota Exceeded: Payment Required"