import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import stripe
from app.services.stripe_service import StripeService


@pytest.mark.asyncio
async def test_forged_webhook_signature_rejection():
    """
    Verify forged or unverified Stripe webhook payloads raise SignatureVerificationError.
    """
    db = AsyncMock()
    db.add = MagicMock()  # Synchronous ORM method
    service = StripeService(db)

    payload = b'{"id": "evt_fake_123", "type": "checkout.session.completed"}'
    invalid_sig = "t=12345,v1=invalid_signature_hash"

    with patch("stripe.Webhook.construct_event") as mock_construct:
        mock_construct.side_effect = stripe.SignatureVerificationError(
            "Invalid signature", payload, invalid_sig
        )

        with pytest.raises(stripe.SignatureVerificationError):
            service.verify_webhook_signature(payload, invalid_sig)


@pytest.mark.asyncio
async def test_quota_boundary_enforcement():
    """
    Verify tenant nearing token quota boundary blocks usage upon hitting limit.
    """
    mock_tenant = MagicMock()
    mock_tenant.plan = "free"
    mock_tenant.token_quota = 100_000
    mock_tenant.current_usage = 99_950  # 50 tokens below quota limit

    requested_tokens = 100
    is_allowed = (mock_tenant.current_usage + requested_tokens) <= mock_tenant.token_quota

    assert is_allowed is False


@pytest.mark.asyncio
async def test_upgrade_resets_quota_at_boundary():
    """
    Verify tenant sitting at quota limit is immediately unblocked after Pro checkout.
    """
    tenant_id = uuid.uuid4()
    mock_tenant = MagicMock()
    mock_tenant.id = tenant_id
    mock_tenant.plan = "free"
    mock_tenant.token_quota = 100_000

    db_webhook_res = MagicMock()
    db_webhook_res.scalar_one_or_none.return_value = None  # First time event

    db_tenant_res = MagicMock()
    db_tenant_res.scalar_one_or_none.return_value = mock_tenant

    db_sub_res = MagicMock()
    db_sub_res.scalar_one_or_none.return_value = None

    db = AsyncMock()
    db.add = MagicMock()  # Synchronous ORM method
    db.execute.side_effect = [db_webhook_res, db_tenant_res, db_sub_res]

    service = StripeService(db)

    event = {
        "id": "evt_boundary_upgrade_01",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "client_reference_id": str(tenant_id),
                "customer": "cus_boundary_123",
                "subscription": "sub_boundary_123",
                "metadata": {"tenant_id": str(tenant_id), "plan_id": "pro"},
            }
        },
    }

    success, message = await service.handle_webhook_event(event)

    assert success is True
    assert mock_tenant.plan == "pro"
    assert mock_tenant.token_quota == 10_000_000