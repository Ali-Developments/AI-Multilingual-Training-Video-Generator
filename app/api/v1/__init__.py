"""API v1 router configuration."""

from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.projects import router as projects_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router, tags=["Health"])
api_v1_router.include_router(projects_router, tags=["Projects"])
