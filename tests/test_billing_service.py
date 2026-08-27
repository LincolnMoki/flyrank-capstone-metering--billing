import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.billing import BillingService


def build_subscription(
    api_call_quota=1_000,
    api_token_quota=100_000,
    status="active",
    plan_tier="FREE",
):
    subscription = MagicMock()
    subscription.api_call_quota = api_call_quota
    subscription.api_token_quota = api_token_quota
    subscription.status = status
    subscription.plan_tier = plan_tier
    return subscription


@pytest.mark.asyncio
async def test_record_usage_success():
    db = AsyncMock()
    db.add = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = True

    tenant = MagicMock()
    tenant.id = uuid.uuid4()
    tenant.is_active = True

    subscription = build_subscription(
        api_call_quota=1_000,
        api_token_quota=100_000,
    )

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant

    subscription_result = MagicMock()
    subscription_result.scalar_one_or_none.return_value = subscription

    usage_result = MagicMock()
    usage_result.one.return_value = MagicMock(
        api_calls=0,
        tokens=0,
    )

    db.execute.side_effect = [
        tenant_result,
        subscription_result,
        usage_result,
    ]

    service = BillingService(db, redis)

    success, status_code, message = await service.record_usage(
        tenant_id=tenant.id,
        idempotency_key="key-123",
        standard_input_tokens=1_000,
        output_tokens=500,
    )

    assert success is True
    assert status_code == 201
    assert message == "Usage Recorded Successfully"

    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_usage_idempotency_duplicate():
    db = AsyncMock()
    db.add = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = False

    service = BillingService(db, redis)

    tenant_id = uuid.uuid4()

    success, status_code, message = await service.record_usage(
        tenant_id=tenant_id,
        idempotency_key="duplicate-key-456",
        tokens_used=500,
    )

    assert success is True
    assert status_code == 200
    assert message == "Duplicated event ignored"

    db.execute.assert_not_awaited()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_record_usage_token_quota_exceeded():
    db = AsyncMock()
    db.add = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = True

    tenant = MagicMock()
    tenant.id = uuid.uuid4()
    tenant.is_active = True

    subscription = build_subscription(
        api_call_quota=1_000,
        api_token_quota=1_000,
    )

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant

    subscription_result = MagicMock()
    subscription_result.scalar_one_or_none.return_value = subscription

    usage_result = MagicMock()
    usage_result.one.return_value = MagicMock(
        api_calls=10,
        tokens=900,
    )

    db.execute.side_effect = [
        tenant_result,
        subscription_result,
        usage_result,
    ]

    service = BillingService(db, redis)

    success, status_code, message = await service.record_usage(
        tenant_id=tenant.id,
        idempotency_key="token-quota-test",
        tokens_used=200,
    )

    assert success is False
    assert status_code == 402
    assert "quota exceeded" in message.lower()

    db.add.assert_not_called()
    db.commit.assert_not_awaited()

    # Failed quota requests must release the Redis idempotency key
    redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_usage_api_call_quota_exceeded():
    db = AsyncMock()
    db.add = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = True

    tenant = MagicMock()
    tenant.id = uuid.uuid4()
    tenant.is_active = True

    subscription = build_subscription(
        api_call_quota=10,
        api_token_quota=100_000,
    )

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant

    subscription_result = MagicMock()
    subscription_result.scalar_one_or_none.return_value = subscription

    usage_result = MagicMock()
    usage_result.one.return_value = MagicMock(
        api_calls=10,
        tokens=50_000,
    )

    db.execute.side_effect = [
        tenant_result,
        subscription_result,
        usage_result,
    ]

    service = BillingService(db, redis)

    success, status_code, message = await service.record_usage(
        tenant_id=tenant.id,
        idempotency_key="call-quota-test",
        tokens_used=100,
    )

    assert success is False
    assert status_code == 402
    assert "quota exceeded" in message.lower()

    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    redis.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_usage_allows_request_at_quota_boundary():
    db = AsyncMock()
    db.add = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = True

    tenant = MagicMock()
    tenant.id = uuid.uuid4()
    tenant.is_active = True

    subscription = build_subscription(
        api_call_quota=10,
        api_token_quota=1_000,
    )

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant

    subscription_result = MagicMock()
    subscription_result.scalar_one_or_none.return_value = subscription

    usage_result = MagicMock()
    usage_result.one.return_value = MagicMock(
        api_calls=9,
        tokens=900,
    )

    db.execute.side_effect = [
        tenant_result,
        subscription_result,
        usage_result,
    ]

    service = BillingService(db, redis)

    success, status_code, message = await service.record_usage(
        tenant_id=tenant.id,
        idempotency_key="boundary-test",
        tokens_used=100,
    )

    assert success is True
    assert status_code == 201
    assert message == "Usage Recorded Successfully"

    db.add.assert_called_once()
    db.commit.assert_awaited_once()