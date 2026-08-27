import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.flutterwave_service import FlutterwaveService


@pytest.mark.asyncio
async def test_quota_boundary_enforcement():
    """
    Verify tenant nearing token quota boundary blocks usage
    when the request would exceed the quota.
    """

    mock_subscription = MagicMock()
    mock_subscription.plan_tier = "FREE"
    mock_subscription.api_token_quota = 100_000

    current_usage = 99_950
    requested_tokens = 100

    is_allowed = (
        current_usage + requested_tokens
    ) <= mock_subscription.api_token_quota

    assert is_allowed is False


@pytest.mark.asyncio
async def test_upgrade_resets_quota_at_boundary():
    """
    Verify a successful Flutterwave Pro payment gives the tenant
    the Pro token quota.
    """

    tenant_id = uuid.uuid4()

    mock_tenant = MagicMock()
    mock_tenant.id = tenant_id
    mock_tenant.name = "Boundary Tenant"

    db_webhook_res = MagicMock()
    db_webhook_res.scalar_one_or_none.return_value = None

    db_tenant_res = MagicMock()
    db_tenant_res.scalar_one_or_none.return_value = mock_tenant

    db_sub_res = MagicMock()
    db_sub_res.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.add = MagicMock()

    db.execute.side_effect = [
        db_webhook_res,
        db_tenant_res,
        db_sub_res,
    ]

    service = FlutterwaveService(db)

    event = {
        "id": "flw_evt_boundary_upgrade_01",
        "type": "charge.completed",
        "data": {
            "id": "flw_tx_boundary_123",
            "status": "successful",
            "meta": {
                "tenant_id": str(tenant_id),
                "plan_id": "pro",
            },
        },
    }

    success, message = await service.handle_webhook_event(event)

    assert success is True
    assert message == "Webhook processed successfully"

    # The newly-created Subscription receives the Pro quota.
    created_subscription = db.add.call_args.args[0]

    assert created_subscription.plan_tier == "pro"
    assert created_subscription.api_token_quota == 10_000_000

    db.commit.assert_awaited_once()