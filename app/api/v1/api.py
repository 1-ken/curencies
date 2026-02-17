"""API v1 router configuration."""
from fastapi import APIRouter

from .endpoints import alerts, data

# Create main router
router = APIRouter(prefix="/api/v1")

# Include endpoint routers
router.include_router(alerts.router)

# Data endpoints don't have a prefix, they're added separately in main.py for root paths

__all__ = ["router", "data"]
