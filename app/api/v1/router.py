from fastapi import APIRouter
from app.api.v1 import usage

api_router = APIRouter()
api_router.include_router(usage.router, prefix="/usage", tags=["Usage"])