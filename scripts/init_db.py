import asyncio
import os
import sys
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings


async def init_models():
    engine = create_async_engine(settings.async_database_url)
    async with engine.connect() as connection:
        existing_tables = await connection.run_sync(
            lambda sync_connection: set(inspect(sync_connection).get_table_names())
        )
    await engine.dispose()

    config = Config("alembic.ini")
    expected_tables = {"tenants", "subscriptions", "usage_events", "webhook_logs"}

    if "alembic_version" in existing_tables and "plans" in existing_tables:
        # Recover safely if an earlier bootstrap stamped the legacy schema at
        # 0001 but completed the plans migration before being interrupted.
        await asyncio.to_thread(command.stamp, config, "head")
        print("Existing migrated schema stamped at the migration head.")
    elif "alembic_version" in existing_tables:
        await asyncio.to_thread(command.upgrade, config, "head")
        print("Database migrations are at the migration head.")
    elif expected_tables.issubset(existing_tables):
        await asyncio.to_thread(command.stamp, config, "0001_initial_schema")
        await asyncio.to_thread(command.upgrade, config, "head")
        print("Existing schema stamped and upgraded to the migration head.")
    else:
        await asyncio.to_thread(command.upgrade, config, "head")
        print("Database migrations applied successfully!")


if __name__ == "__main__":
    asyncio.run(init_models())
