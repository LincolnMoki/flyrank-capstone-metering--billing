from fastapi import FastAPI
from app.api.v1.billing import router as billing_router

app = FastAPI(title="FlyRank Metering & Billing API")

app.include_router(billing_router, prefix="/api/v1")