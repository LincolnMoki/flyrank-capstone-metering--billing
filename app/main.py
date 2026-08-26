from fastapi import FastAPI
from app.api.v1.billing import router as billing_router
from app.api.v1.usage import router as usage_router

app = FastAPI(title="FlyRank Metering & Billing API", version="0.1.0")

app.include_router(billing_router, prefix="/api/v1/billing", tags=["billing"])
app.include_router(usage_router, prefix="/api/v1/usage", tags=["usage"])
