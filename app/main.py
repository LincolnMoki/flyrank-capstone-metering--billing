from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from arq import create_pool
from fastapi import FastAPI

from app.api.v1.billing import router as billing_router
from app.api.v1.router import api_router
from app.core.config import settings
from app.workers.worker import REDIS_SETTINGS


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis client used by application services
    app.state.redis = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
    )

    # ARQ Redis connection pool
    app.state.arq_pool = await create_pool(REDIS_SETTINGS)

    yield

    await app.state.redis.close()
    await app.state.arq_pool.close()


app = FastAPI(
    title="FlyRank Metering & Billing API",
    description=(
        "API for AI usage metering, monthly quota enforcement, "
        "cost tracking, asynchronous usage processing, and Stripe billing."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(
    billing_router,
    prefix="/api/v1/billing",
    tags=["billing"],
)

app.include_router(
    api_router,
    prefix="/api/v1",
)