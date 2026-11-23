"""Event endpoints — refills, suspected drains, low-fuel and engine transitions.

This is the feed a billing or alerting consumer subscribes to. Refills are what
gets invoiced; suspected drains are what gets investigated.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_organisation
from app.db import get_session
from app.models.entities import Event, EventType, Generator, Organisation, Tank
from app.schemas import EventOut, EventPage

router = APIRouter(prefix="/v1", tags=["events"])

DEFAULT_LIMIT = 200
MAX_LIMIT = 2_000


@router.get("/events", response_model=EventPage, summary="List events, newest first")
async def list_events(
    generator_id: uuid.UUID | None = Query(default=None),
    tank_id: uuid.UUID | None = Query(default=None, description="Filter to one tank."),
    vehicle_id: uuid.UUID | None = Query(default=None, description="Filter to one vehicle."),
    site_id: uuid.UUID | None = Query(
        default=None, description="Filter to everything that happened at one site, either tier."
    ),
    event_type: list[EventType] | None = Query(
        default=None, description="Repeatable. Omit for all types."
    ),
    start: datetime | None = Query(default=None, description="Inclusive lower bound."),
    end: datetime | None = Query(default=None, description="Exclusive upper bound."),
    before: datetime | None = Query(default=None, description="Keyset cursor."),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> EventPage:
    query = select(Event).where(Event.organisation_id == organisation.id)

    if generator_id is not None:
        query = query.where(Event.generator_id == generator_id)
    if tank_id is not None:
        query = query.where(Event.tank_id == tank_id)
    if vehicle_id is not None:
        query = query.where(Event.vehicle_id == vehicle_id)
    if site_id is not None:
        # A site's events reach it by two different routes: engine transitions
        # hang off a generator, while a delivery into shared bulk storage
        # carries a tank and no generator at all. Matching on either side is
        # what makes this the site's whole story rather than half of it.
        query = query.where(
            or_(
                Event.tank_id.in_(
                    select(Tank.id).where(
                        Tank.site_id == site_id, Tank.organisation_id == organisation.id
                    )
                ),
                Event.generator_id.in_(
                    select(Generator.id).where(
                        Generator.site_id == site_id,
                        Generator.organisation_id == organisation.id,
                    )
                ),
            )
        )
    if event_type:
        query = query.where(Event.event_type.in_(event_type))
    if start is not None:
        query = query.where(Event.occurred_at >= start)
    if end is not None:
        query = query.where(Event.occurred_at < end)
    if before is not None:
        query = query.where(Event.occurred_at < before)

    rows = list(
        (await session.execute(query.order_by(Event.occurred_at.desc()).limit(limit + 1)))
        .scalars()
        .all()
    )

    has_more = len(rows) > limit
    page = rows[:limit]

    return EventPage(
        items=[EventOut.model_validate(row) for row in page],
        next_cursor=page[-1].occurred_at if has_more and page else None,
    )
