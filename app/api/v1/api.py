"""API v1 router configuration."""
from fastapi import APIRouter

from .endpoints import admin, alerts, auth, data, favorites

# Create main router
router = APIRouter(prefix="/api/v1")

# Include endpoint routers
router.include_router(auth.router)
router.include_router(alerts.router)
router.include_router(favorites.router)
router.include_router(admin.router)

# Data endpoints don't have a prefix, they're added separately in main.py for root paths

__all__ = ["router", "data"]
