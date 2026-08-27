import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()
engine = create_async_engine(settings.async_database_url, echo=False)

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.db.session import Base 
from sqlalchemy.ext.asyncio import create_async_engine


async def init_models():
    engine = create_async_engine(settings.async_database_url, echo=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Database tables created successfully!")


if __name__ == "__main__":
    asyncio.run(init_models())