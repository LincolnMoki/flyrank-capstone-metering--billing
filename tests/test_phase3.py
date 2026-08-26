import uuid
from unittest.mock import AsyncMock, MagicMock
import pytest
from app.services.stripe_service import StripeService


@pytest.mark.asyncio
async def test_checkout_flips_tenant_free_to_pro():
    """
    Phase 3 Gate Test: Verify test checkout webhook completion flips tenant from 'free' to 'pro'.
    """
    db = AsyncMock()
    db.add = MagicMock()

    tenant_id = uuid.uuid4()
    mock_tenant = MagicMock()
    mock_tenant.id = tenant_id
    mock_tenant.plan = "free"
    mock_tenant.token_quota = 100_000

    db_webhook_res = MagicMock()
    db_webhook_res.scalar_one_or_none.return_value = None  # No prior webhook log

    db_tenant_res = MagicMock()
    db_tenant_res.scalar_one_or_none.return_value = mock_tenant

    db_sub_res = MagicMock()
    db_sub_res.scalar_one_or_none.return_value = None  # No prior subscription

    db.execute.side_effect = [db_webhook_res, db_tenant_res, db_sub_res]

    service = StripeService(db)

    webhook_event = {
        "id": "evt_test_checkout_101",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": str(tenant_id),
                "customer": "cus_test123",
                "subscription": "sub_test123",
                "metadata": {"tenant_id": str(tenant_id), "plan_id": "pro"},
            }
        },
    }

    success, message = await service.handle_webhook_event(webhook_event)

    assert success is True
    assert message == "Webhook processed successfully"
    assert mock_tenant.plan == "pro"
    assert mock_tenant.token_quota == 10_000_000
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_webhook_deduplication():
    """
    Verify duplicate webhook event IDs are detected and ignored without secondary DB modifications.
    """
    db = AsyncMock()

    db_webhook_res = MagicMock()
    db_webhook_res.scalar_one_or_none.return_value = MagicMock()  # Log exists!

    db.execute.return_value = db_webhook_res

    service = StripeService(db)

    webhook_event = {
        "id": "evt_test_checkout_101",
        "type": "checkout.session.completed",
        "data": {},
    }

    success, message = await service.handle_webhook_event(webhook_event)

    assert success is True
    assert message == "Duplicate webhook event ignored"
    db.add.assert_not_called()

@pytest.mark.asyncio
async def test_subscription_deleted_returns_tenant_to_free():
    """
    Verify a deleted Stripe subscription returns the tenant
    to the Free plan and restores the Free token quota.
    """
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    # Webhook has not been processed before
    db_webhook_res = MagicMock()
    db_webhook_res.scalar_one_or_none.return_value = None

    # Existing Pro tenant
    mock_tenant = MagicMock()
    mock_tenant.plan = "pro"
    mock_tenant.token_quota = 10_000_000

    db_tenant_res = MagicMock()
    db_tenant_res.scalar_one_or_none.return_value = mock_tenant

    # Existing Pro subscription
    mock_subscription = MagicMock()
    mock_subscription.plan_tier = "pro"
    mock_subscription.status = "active"
    mock_subscription.api_token_quota = 10_000_000

    db_sub_res = MagicMock()
    db_sub_res.scalar_one_or_none.return_value = mock_subscription

    db.execute.side_effect = [
        db_webhook_res,
        db_tenant_res,
        db_sub_res,
    ]

    service = StripeService(db)

    tenant_id = uuid.uuid4()

    webhook_event = {
        "id": "evt_subscription_deleted_001",
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_test_123",
                "metadata": {
                    "tenant_id": str(tenant_id),
                },
            }
        },
    }

    success, message = await service.handle_webhook_event(webhook_event)

    assert success is True
    assert message == "Webhook processed successfully"

    assert mock_tenant.plan == "free"
    assert mock_tenant.token_quota == 100_000

    assert mock_subscription.plan_tier == "free"
    assert mock_subscription.status == "canceled"
    assert mock_subscription.api_token_quota == 100_000

    db.add.assert_called_once()
    db.commit.assert_awaited_once()