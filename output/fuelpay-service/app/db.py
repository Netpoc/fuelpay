"""Database wiring.

The engine and sessionmaker are created lazily rather than at import time.
That keeps `import app.models` — and therefore the pure simulation code and its
tests — from requiring a reachable database or even an installed driver.
"""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=settings.echo_sql,
        pool_pre_ping=True,
        # date_trunc on a timestamptz resolves in the session time zone, so the
        # daily rollups in app/api/analytics.py would silently re-bucket if the
        # server's TZ were anything else. Pin it rather than inherit it.
        connect_args={"server_settings": {"timezone": "UTC"}},
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Release pooled connections on shutdown."""
    await get_engine().dispose()
