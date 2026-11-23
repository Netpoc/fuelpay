"""Liveness and readiness. Unauthenticated — orchestrators do not carry keys."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Answers as long as the process is up. Never touches the database."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe")
async def ready(response: Response, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    """Reports database reachability, so a rolling deploy waits for a usable pod."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 — the reason is reported, not swallowed
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "unreachable", "detail": str(exc)[:200]}

    return {"status": "ok", "database": "ok"}
