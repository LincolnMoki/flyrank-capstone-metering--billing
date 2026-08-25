import uuid
import pytest
from app.core.config import settings, calculate_cost_microcents, PlanTier
from app.db.session import Base
from app.models.entities import Tenant, Subscription, UsageEvent, WebhookLog

def test_microcents_math():
    # 450 std ($0.00135) + 3200 cached ($0.0048) + 850 out ($0.01275) + 600 reasoning ($0.009) = 2,790,000 microcents ($0.0279)
    cost = calculate_cost_microcents(
        standard_input_tokens=450,
        cached_input_tokens=3200,
        output_tokens=850,
        reasoning_tokens=600,
    )
    assert cost == 2_790_000
    assert isinstance(cost, int)

def test_entity_instantiation():
    tenant_id = uuid.uuid4
    tenant = Tenant(
        id=tenant_id,
        name="Smile Clinic",
        api_key="dk_test_12345",
        is_active=True,
    )
    assert tenant.id == tenant_id
    assert tenant.name == "Smile Clinic"

def test_table_names():
    assert Tenant.__tablename__ == "tenants"
    assert Subscription.__tablename__ == "subscriptions"
    assert UsageEvent.__tablename__ == "usage_events"
    assert WebhookLog.__tablename__ == "webhook_logs"