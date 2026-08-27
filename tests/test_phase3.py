import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.flutterwave_service import FlutterwaveService


@pytest.mark.asyncio
async def test_checkout_flips_tenant_free_to_pro():
    """
    Phase 3 Gate Test:
    Verify Flutterwave charge completion upgrades a tenant to Pro.
    """

    db = AsyncMock()
    db.add = MagicMock()

    tenant_id = uuid.uuid4()

    mock_tenant = MagicMock()
    mock_tenant.id = tenant_id
    mock_tenant.name = "Test Tenant"

    db_webhook_res = MagicMock()
    db_webhook_res.scalar_one_or_none.return_value = None

    db_tenant_res = MagicMock()
    db_tenant_res.scalar_one_or_none.return_value = mock_tenant

    db_sub_res = MagicMock()
    db_sub_res.scalar_one_or_none.return_value = None

    db.execute.side_effect = [
        db_webhook_res,
        db_tenant_res,
        db_sub_res,
    ]

    service = FlutterwaveService(db)

    webhook_event = {
        "id": "flw_evt_test_101",
        "type": "charge.completed",
        "data": {
            "id": "flw_tx_101",
            "status": "successful",
            "meta": {
                "tenant_id": str(tenant_id),
                "plan_id": "pro",
            },
            "customer": {
                "id": "flw_customer_123",
            },
        },
    }

    success, message = await service.handle_webhook_event(
        webhook_event
    )

    assert success is True
    assert message == "Webhook processed successfully"

    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_webhook_deduplication():
    """
    Verify duplicate Flutterwave webhook IDs are ignored.
    """

    db = AsyncMock()

    db_webhook_res = MagicMock()
    db_webhook_res.scalar_one_or_none.return_value = MagicMock()

    db.execute.return_value = db_webhook_res

    service = FlutterwaveService(db)

    webhook_event = {
        "id": "flw_evt_duplicate_101",
        "type": "charge.completed",
        "data": {},
    }

    success, message = await service.handle_webhook_event(
        webhook_event
    )

    assert success is True
    assert message == "Duplicate webhook event ignored"

    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_payment_not_successful_does_not_upgrade():
    """
    Verify unsuccessful Flutterwave payments do not upgrade a tenant.
    """

    db = AsyncMock()
    db.add = MagicMock()

    db_webhook_res = MagicMock()
    db_webhook_res.scalar_one_or_none.return_value = None

    db.execute.return_value = db_webhook_res

    service = FlutterwaveService(db)

    webhook_event = {
        "id": "flw_evt_failed_101",
        "type": "charge.completed",
        "data": {
            "status": "failed",
        },
    }

    success, message = await service.handle_webhook_event(
        webhook_event
    )

    assert success is True
    assert message == "Payment not successful"

    db.commit.assert_awaited_once()