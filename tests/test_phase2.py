import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.billing import BillingService


def make_subscription(api_call_quota=1_000, api_token_quota=100_000):
    subscription = MagicMock()
    subscription.api_call_quota = api_call_quota
    subscription.api_token_quota = api_token_quota
    subscription.status = "active"
    subscription.plan_tier = "FREE"
    return subscription


@pytest.mark.asyncio
async def test_double_count_prevention():
    """
    Duplicate idempotency keys must mirror the original successful response
    without recording usage again.
    """
    db = AsyncMock()
    db.add = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = False

    service = BillingService(db, redis)

    tenant_id = uuid.uuid4()

    success, status_code, msg = await service.record_usage(
        tenant_id,
        "evt_123",
        standard_input_tokens=500,
    )

    assert success is True
    assert status_code == 201
    assert msg == "Usage Recorded Successfully"

    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_quota_exceeded_returns_429():
    """
    Verify exceeding the monthly token quota returns
        HTTP 429 Too Many Requests.
    """
    db = AsyncMock()
    db.add = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = True

    tenant = MagicMock()
    tenant.id = uuid.uuid4()
    tenant.is_active = True

    subscription = make_subscription(
        api_call_quota=1_000,
        api_token_quota=1_000,
    )

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant

    subscription_result = MagicMock()
    subscription_result.scalar_one_or_none.return_value = subscription

    usage_result = MagicMock()
    usage_result.one.return_value = MagicMock(
        api_calls=100,
        tokens=900,
    )

    db.execute.side_effect = [
        tenant_result,
        subscription_result,
        usage_result,
    ]

    service = BillingService(db, redis)

    success, status_code, msg = await service.record_usage(
        tenant.id,
        "evt_124",
        standard_input_tokens=200,
    )

    assert success is False
    assert status_code == 429
    assert "quota exceeded" in msg.lower()


@pytest.mark.asyncio
async def test_quota_uses_current_month_only():
    """
    Verify quota enforcement uses only current-month usage.

    Previous month:
        80,000 tokens

    Current month:
        30,000 tokens

    Monthly quota:
        100,000 tokens

    New request:
        10,000 tokens

    Expected:
        30,000 + 10,000 = 40,000

    The previous month's 80,000 tokens must not affect
    the current quota calculation.
    """
    db = AsyncMock()
    db.add = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = True

    tenant = MagicMock()
    tenant.id = uuid.uuid4()
    tenant.is_active = True

    subscription = make_subscription(
        api_call_quota=1_000,
        api_token_quota=100_000,
    )

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant

    subscription_result = MagicMock()
    subscription_result.scalar_one_or_none.return_value = subscription

    usage_result = MagicMock()
    usage_result.one.return_value = MagicMock(
        api_calls=30,
        tokens=30_000,
    )

    db.execute.side_effect = [
        tenant_result,
        subscription_result,
        usage_result,
    ]

    service = BillingService(db, redis)

    success, status_code, msg = await service.record_usage(
        tenant_id=tenant.id,
        idempotency_key="evt_month_boundary",
        standard_input_tokens=10_000,
    )

    assert success is True
    assert status_code == 201
    assert msg == "Usage Recorded Successfully"

    assert db.execute.call_count == 3

    usage_query = db.execute.call_args_list[2].args[0]
    query_text = str(usage_query)

    assert "created_at" in query_text
