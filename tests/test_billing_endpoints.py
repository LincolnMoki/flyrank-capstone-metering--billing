import uuid
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient, ASGITransport
import stripe

from app.main import app
from app.db.session import get_db

# Mock database dependency override for FastAPI routes
async def override_get_db():
    mock_db = AsyncMock()
    yield mock_db

app.dependency_overrides[get_db] = override_get_db


@pytest.mark.asyncio
async def test_create_checkout_endpoint_success():
    """Verify POST /api/v1/billing/checkout returns 200 and session details."""
    tenant_id = str(uuid.uuid4())
    payload = {
        "tenant_id": tenant_id,
        "plan_id": "pro",
        "success_url": "https://example.com/success",
        "cancel_url": "https://example.com/cancel",
    }

    mock_response = {
        "session_id": "cs_test_12345",
        "checkout_url": "https://checkout.stripe.com/pay/cs_test_12345",
    }

    with patch(
        "app.services.stripe_service.StripeService.create_checkout_session",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/billing/checkout", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "cs_test_12345"
    assert "checkout_url" in data


@pytest.mark.asyncio
async def test_stripe_webhook_endpoint_success():
    """Verify POST /api/v1/billing/webhooks/stripe processes event successfully."""
    headers = {"stripe-signature": "t=123,v1=test_signature"}
    raw_payload = b'{"id": "evt_test_101", "type": "checkout.session.completed"}'

    with patch(
        "app.services.stripe_service.StripeService.verify_webhook_signature",
        return_value={"id": "evt_test_101", "type": "checkout.session.completed"},
    ), patch(
        "app.services.stripe_service.StripeService.handle_webhook_event",
        new_callable=AsyncMock,
        return_value=(True, "Webhook processed successfully"),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/billing/webhooks/stripe",
                content=raw_payload,
                headers=headers,
            )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["detail"] == "Webhook processed successfully"


@pytest.mark.asyncio
async def test_stripe_webhook_missing_signature_returns_400():
    """Verify missing stripe-signature header returns HTTP 400 Bad Request."""
    raw_payload = b'{"id": "evt_test_101", "type": "checkout.session.completed"}'

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/billing/webhooks/stripe",
            content=raw_payload,
        )

    assert response.status_code == 400
    assert "Missing stripe-signature header" in response.json()["detail"]


@pytest.mark.asyncio
async def test_stripe_webhook_invalid_signature_returns_400():
    """Verify invalid signature handling produces HTTP 400."""
    headers = {"stripe-signature": "t=123,v1=invalid_signature"}
    raw_payload = b'{"id": "evt_test_101"}'

    with patch(
        "app.services.stripe_service.StripeService.verify_webhook_signature",
        side_effect=stripe.error.SignatureVerificationError(
            "Invalid signature", sig_header="t=123,v1=invalid_signature"
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/billing/webhooks/stripe",
                content=raw_payload,
                headers=headers,
            )

    assert response.status_code == 400
    assert "Invalid webhook signature" in response.json()["detail"]