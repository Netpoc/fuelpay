"""Router assembly. `app.main` mounts this one object."""

from fastapi import APIRouter

from app.api import (
    admin,
    analytics,
    demo,
    events,
    fleet,
    health,
    platform,
    tanks,
    telemetry,
    vehicles,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(fleet.router)
api_router.include_router(tanks.router)
api_router.include_router(telemetry.router)
api_router.include_router(events.router)
api_router.include_router(analytics.router)
api_router.include_router(admin.router)
api_router.include_router(vehicles.router)
api_router.include_router(demo.router)
api_router.include_router(platform.router)

__all__ = ["api_router"]
