import asyncio
import os
import sys
import uuid
from dotenv import load_dotenv
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.models.entities import Subscription, Tenant, UsageEvent

DEMO_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def seed_demo_tenant():
    db_url = settings.async_database_url
    print(f"Connecting to: {db_url}")

    engine = create_async_engine(db_url, echo=False)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # This script owns the fixed demo tenant, so reset only its metering
        # data to make repeated seeding deterministic for the live demo.
        await session.execute(
            delete(UsageEvent).where(UsageEvent.tenant_id == DEMO_TENANT_ID)
        )

        result = await session.execute(
            select(Tenant).where(Tenant.id == DEMO_TENANT_ID)
        )
        tenant = result.scalar_one_or_none()

        if tenant:
            tenant.name = "Demo Boundary Tenant"
            tenant.is_active = True
            print(f"Updated existing demo tenant: {tenant.id}")
        else:
            tenant = Tenant(
                id=DEMO_TENANT_ID,
                name="Demo Boundary Tenant",
                api_key="demo_api_key_000000000001",
                is_active=True,
            )
            session.add(tenant)
            print(f"Created new demo tenant: {tenant.id}")

        await session.flush()
        sub_result = await session.execute(
        select(Subscription).where(Subscription.tenant_id == DEMO_TENANT_ID)
        )
        subscription = sub_result.scalar_one_or_none()

        if subscription:
            subscription.plan_tier = "FREE"
            subscription.status = "active"
            subscription.api_call_quota = 10
            subscription.api_token_quota = 1_000
        else:
            subscription = Subscription(
                tenant_id=DEMO_TENANT_ID,
                plan_tier="FREE",
                status="active",
                api_call_quota=10,
                api_token_quota=1_000,
            )
            session.add(subscription)

        await session.commit()
        print(f"Subscription: {subscription.plan_tier} | calls={subscription.api_call_quota} tokens={subscription.api_token_quota}")

        print("\n--- Demo Tenant Seeded Successfully ---")
        print(f"Tenant ID: {tenant.id}")
        print(f"Name:      {tenant.name}")
        print(f"API Key:   {tenant.api_key}")
        print(f"Active:    {tenant.is_active}")
        print("---------------------------------------")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_demo_tenant())
