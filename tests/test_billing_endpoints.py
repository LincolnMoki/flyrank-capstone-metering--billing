import uuid

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.session import get_db


async def override_get_db():
    mock_tenant = MagicMock()
    mock_tenant.is_active = True

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_tenant

    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    yield mock_db


app.dependency_overrides[get_db] = override_get_db


@pytest.mark.asyncio
async def test_create_checkout_endpoint_success():
    """
    Verify POST /api/v1/billing/checkout returns
    a Flutterwave checkout session.
    """

    tenant_id = str(uuid.uuid4())

    payload = {
        "plan_id": "pro",
        "success_url": "https://example.com/success",
        "cancel_url": "https://example.com/cancel",
    }

    mock_response = {
        "session_id": "flyrank-pro-test-123",
        "checkout_url": "https://checkout.flutterwave.com/pay/test123",
    }

    with patch(
        "app.api.v1.billing.FlutterwaveService.create_checkout_session",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        

        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:

            response = await client.post(
                "/api/v1/billing/checkout",
                json=payload,
                headers={"X-API-Key": "test-key"},
            )

    assert response.status_code == 200

    data = response.json()

    assert data["session_id"] == "flyrank-pro-test-123"
    assert "checkout_url" in data


@pytest.mark.asyncio
async def test_flutterwave_webhook_endpoint_success():
    """
    Verify POST /api/v1/billing/webhooks/flutterwave
    processes a valid Flutterwave webhook.
    """

    tenant_id = str(uuid.uuid4())

    headers = {
        "verif-hash": "test-secret-hash",
    }

    payload = {
        "id": "flw_evt_test_101",
        "type": "charge.completed",
        "data": {
            "id": "flw_tx_101",
            "status": "successful",
            "meta": {
                "tenant_id": tenant_id,
                "plan_id": "pro",
            },
        },
    }

    with patch(
        "app.api.v1.billing.settings.FLW_SECRET_HASH",
        "test-secret-hash",
    ), patch(
        "app.api.v1.billing.FlutterwaveService.handle_webhook_event",
        new_callable=AsyncMock,
        return_value=(
            True,
            "Webhook processed successfully",
        ),
    ):

        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:

            response = await client.post(
                "/api/v1/billing/webhooks/flutterwave",
                json=payload,
                headers=headers,
            )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "success"
    assert data["detail"] == "Webhook processed successfully"


@pytest.mark.asyncio
async def test_flutterwave_webhook_missing_signature_returns_400():
    """
    Verify missing Flutterwave verif-hash is rejected.
    """
    payload = {
        "id": "flw_evt_test_101",
        "type": "charge.completed",
    }

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:

        response = await client.post(
            "/api/v1/billing/webhooks/flutterwave",
            json=payload,
        )

    assert response.status_code == 400

    assert (
        "Missing Flutterwave webhook signature"
        in response.json()["detail"]
    )


@pytest.mark.asyncio
async def test_flutterwave_webhook_invalid_signature_returns_400():
    """
    Verify an invalid Flutterwave verif-hash is rejected.
    """
    headers = {
        "verif-hash": "invalid-hash",
    }

    payload = {
        "id": "flw_evt_test_101",
        "type": "charge.completed",
    }

    with patch(
        "app.api.v1.billing.settings.FLW_SECRET_HASH",
        "correct-hash",
    ):

        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:

            response = await client.post(
                "/api/v1/billing/webhooks/flutterwave",
                json=payload,
                headers=headers,
            )

    assert response.status_code == 400

    assert (
        "Invalid Flutterwave webhook signature"
        in response.json()["detail"]
    )
