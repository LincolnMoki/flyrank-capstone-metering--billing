import asyncio
import os
import sys
import uuid
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.db.session import Base
from app.models.entities import Tenant

DEMO_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def seed_demo_tenant():
    db_url = settings.async_database_url
    print(f"Connecting to: {db_url}")

    engine = create_async_engine(db_url, echo=False)

    async with engine.begin() as conn:
        print("Ensuring database tables exist...")
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
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

        await session.commit()

        print("\n--- Demo Tenant Seeded Successfully ---")
        print(f"Tenant ID: {tenant.id}")
        print(f"Name:      {tenant.name}")
        print(f"API Key:   {tenant.api_key}")
        print(f"Active:    {tenant.is_active}")
        print("---------------------------------------")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_demo_tenant())