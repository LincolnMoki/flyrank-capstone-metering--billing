from fastapi import FastAPI
from app.api.v1.billing import router as billing_router
from app.api.v1.usage import router as usage_router
from app.api.v1.router import api_router
from arq import create_pool
from app.workers.worker import REDIS_SETTINGS
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize ARQ Redis connection pool
    app.state.arq_pool = await create_pool(REDIS_SETTINGS)
    yield
    # Shutdown: Close ARQ connection pool
    await app.state.arq_pool.close()

app = FastAPI(title="FlyRank Metering & Billing API", version="0.1.0")

app.include_router(billing_router, prefix="/api/v1/billing", tags=["billing"])
app.include_router(usage_router, prefix="/api/v1/usage", tags=["usage"])
app.include_router(api_router, prefix="/api/v1")