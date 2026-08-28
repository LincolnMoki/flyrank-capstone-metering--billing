import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.session import get_db
from app.services.billing import BillingService


def make_tenant(tenant_id, name, api_key):
    tenant = MagicMock()
    tenant.id = tenant_id
    tenant.name = name
    tenant.api_key = api_key
    tenant.is_active = True
    return tenant


def make_usage_row(total_requests, tokens_consumed, total_microcents):
    row = MagicMock()
    row.total_requests = total_requests
    row.tokens_consumed = tokens_consumed
    row.total_microcents = total_microcents
    return row


@pytest.mark.asyncio
async def test_tenant_cannot_see_another_tenants_usage_totals():
    """
    Tenant isolation (read path): a request authenticated as Tenant A
    must return Tenant A's own totals, and a separate request
    authenticated as Tenant B must return Tenant B's own totals —
    the two must never collide, even though both rows live in the
    same usage_events table.
    """
    tenant_a = make_tenant(uuid.uuid4(), "Tenant A", "key-a")
    tenant_b = make_tenant(uuid.uuid4(), "Tenant B", "key-b")

    transport = ASGITransport(app=app)

    # --- Request authenticated as Tenant A ---
    tenant_a_result = MagicMock()
    tenant_a_result.scalar_one_or_none.return_value = tenant_a

    usage_a_result = MagicMock()
    usage_a_result.one.return_value = make_usage_row(
        total_requests=3, tokens_consumed=300, total_microcents=9_000
    )

    sub_a_result = MagicMock()
    sub_a_result.scalar_one_or_none.return_value = None

    db_a = AsyncMock()
    db_a.execute.side_effect = [tenant_a_result, usage_a_result, sub_a_result]

    async def override_get_db_a():
        yield db_a

    app.dependency_overrides[get_db] = override_get_db_a

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response_a = await client.get(
            "/api/v1/usage", headers={"X-API-Key": "key-a"}
        )

    assert response_a.status_code == 200
    data_a = response_a.json()
    assert data_a["tenant"]["id"] == str(tenant_a.id)
    assert data_a["usage"]["total_requests"] == 3

    # The query actually executed for the usage rollup must be scoped
    # to Tenant A's id specifically — this is the real isolation
    # guarantee, not just the shape of the response.
    usage_query_a = db_a.execute.call_args_list[1].args[0]
    bound_params_a = usage_query_a.compile().params
    assert tenant_a.id in bound_params_a.values()
    assert tenant_b.id not in bound_params_a.values()

    # --- Separate request authenticated as Tenant B ---
    tenant_b_result = MagicMock()
    tenant_b_result.scalar_one_or_none.return_value = tenant_b

    usage_b_result = MagicMock()
    usage_b_result.one.return_value = make_usage_row(
        total_requests=99, tokens_consumed=99_000, total_microcents=500_000
    )

    sub_b_result = MagicMock()
    sub_b_result.scalar_one_or_none.return_value = None

    db_b = AsyncMock()
    db_b.execute.side_effect = [tenant_b_result, usage_b_result, sub_b_result]

    async def override_get_db_b():
        yield db_b

    app.dependency_overrides[get_db] = override_get_db_b

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response_b = await client.get(
            "/api/v1/usage", headers={"X-API-Key": "key-b"}
        )

    assert response_b.status_code == 200
    data_b = response_b.json()
    assert data_b["tenant"]["id"] == str(tenant_b.id)
    assert data_b["usage"]["total_requests"] == 99

    usage_query_b = db_b.execute.call_args_list[1].args[0]
    bound_params_b = usage_query_b.compile().params
    assert tenant_b.id in bound_params_b.values()
    assert tenant_a.id not in bound_params_b.values()

    # The two tenants' totals must never collide.
    assert data_a["usage"]["total_requests"] != data_b["usage"]["total_requests"]
    assert data_a["tenant"]["id"] != data_b["tenant"]["id"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_record_usage_quota_check_scoped_to_authenticated_tenant_only():
    """
    Tenant isolation (write path): BillingService.record_usage's
    monthly usage aggregation — the query that decides whether a
    request is within quota — must filter by the authenticated
    tenant's own id. One tenant's activity must never be able to
    inflate or exhaust another tenant's quota.
    """
    db = AsyncMock()
    db.add = MagicMock()

    redis = AsyncMock()
    redis.set.return_value = True

    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()

    tenant = MagicMock()
    tenant.id = tenant_a_id
    tenant.is_active = True

    subscription = MagicMock()
    subscription.api_call_quota = 1_000
    subscription.api_token_quota = 100_000
    subscription.status = "active"

    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = tenant

    subscription_result = MagicMock()
    subscription_result.scalar_one_or_none.return_value = subscription

    usage_result = MagicMock()
    usage_result.one.return_value = MagicMock(api_calls=0, tokens=0)

    db.execute.side_effect = [tenant_result, subscription_result, usage_result]

    service = BillingService(db, redis)

    success, status_code, message = await service.record_usage(
        tenant_id=tenant_a_id,
        idempotency_key="isolation-check",
        standard_input_tokens=10,
    )

    assert success is True
    assert status_code == 201

    usage_query = db.execute.call_args_list[2].args[0]
    bound_params = usage_query.compile().params

    assert tenant_a_id in bound_params.values()
    assert tenant_b_id not in bound_params.values()