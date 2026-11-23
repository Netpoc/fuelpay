"""Rollups: fleet posture now, and consumption per day.

Daily buckets come from date_trunc rather than Timescale's time_bucket so these
endpoints keep working on stock PostgreSQL. Buckets are UTC — date_trunc on a
timestamptz resolves in the session time zone, which the service pins to UTC.

Because `consumed_l` is recorded per reading, daily burn is a plain SUM. Doing
it from level deltas instead would count every refill as negative consumption.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Float, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_organisation
from app.db import get_session
from app.models.entities import Event, EventType, Generator, GeneratorStatus, Organisation, Reading
from app.schemas import DailyConsumption, FleetSummary, GeneratorConsumption

router = APIRouter(prefix="/v1", tags=["analytics"])


@router.get("/summary", response_model=FleetSummary, summary="Fleet posture right now")
async def fleet_summary(
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> FleetSummary:
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)

    generators = list(
        (
            await session.execute(
                select(Generator).where(
                    Generator.organisation_id == organisation.id,
                    Generator.status == GeneratorStatus.ACTIVE,
                )
            )
        )
        .scalars()
        .all()
    )

    latest = list(
        (
            await session.execute(
                select(Reading)
                .where(Reading.organisation_id == organisation.id)
                .distinct(Reading.generator_id)
                .order_by(Reading.generator_id, Reading.time.desc())
            )
        )
        .scalars()
        .all()
    )
    by_generator = {reading.generator_id: reading for reading in latest}

    # Cross-referencing thresholds in Python keeps the SQL simple and is fine
    # at demo-fleet scale. For thousands of generators this belongs in a
    # lateral join against the latest reading per unit.
    total_fuel = 0.0
    running = 0
    below_threshold = 0
    total_capacity = 0.0

    for generator in generators:
        total_capacity += generator.tank_capacity_l
        reading = by_generator.get(generator.id)
        if reading is None:
            continue
        total_fuel += reading.fuel_level_l
        if reading.engine_running:
            running += 1
        if reading.fuel_level_pct < generator.reorder_threshold_pct:
            below_threshold += 1

    consumed = (
        await session.execute(
            select(func.coalesce(func.sum(Reading.consumed_l), 0.0)).where(
                Reading.organisation_id == organisation.id,
                Reading.time >= since,
            )
        )
    ).scalar_one()

    volumes = (
        await session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case((Event.event_type == EventType.REFILL, Event.volume_l), else_=0.0)
                    ),
                    0.0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (Event.event_type == EventType.SUSPECTED_DRAIN, Event.volume_l),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ),
            ).where(
                Event.organisation_id == organisation.id,
                Event.occurred_at >= since,
                # The fleet summary is about generator fuel; a tractor's
                # refuels and siphons are reported on the vehicle.
                Event.vehicle_id.is_(None),
            )
        )
    ).one()
    refilled, drained = volumes

    return FleetSummary(
        generator_count=len(generators),
        running_count=running,
        total_capacity_l=round(total_capacity, 1),
        total_fuel_l=round(total_fuel, 1),
        fill_pct=round((total_fuel / total_capacity) * 100.0, 2) if total_capacity else 0.0,
        below_reorder_threshold=below_threshold,
        consumed_l_24h=round(float(consumed), 2),
        refilled_l_24h=round(float(refilled), 2),
        # Drain volumes are stored negative; report the magnitude taken.
        drained_l_24h=round(abs(float(drained)), 2),
        as_of=now,
    )


@router.get(
    "/generators/{generator_id}/consumption",
    response_model=GeneratorConsumption,
    summary="Daily consumption, refills and drains for one generator",
)
async def generator_consumption(
    generator_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=365, description="Days of history to roll up."),
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> GeneratorConsumption:
    generator = (
        await session.execute(
            select(Generator).where(
                Generator.id == generator_id,
                Generator.organisation_id == organisation.id,
            )
        )
    ).scalar_one_or_none()

    if generator is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generator not found.")

    since = datetime.now(UTC) - timedelta(days=days)
    day_column = func.date_trunc("day", Reading.time).label("day")

    burn_rows = (
        await session.execute(
            select(
                day_column,
                func.sum(Reading.consumed_l),
                func.sum(Reading.runtime_minutes) / 60.0,
            )
            .where(Reading.generator_id == generator_id, Reading.time >= since)
            .group_by(day_column)
            .order_by(day_column)
        )
    ).all()

    event_day = func.date_trunc("day", Event.occurred_at).label("day")
    event_rows = (
        await session.execute(
            select(
                event_day,
                func.coalesce(
                    func.sum(
                        case((Event.event_type == EventType.REFILL, Event.volume_l), else_=0.0)
                    ),
                    0.0,
                ).cast(Float),
                func.coalesce(
                    func.sum(
                        case(
                            (Event.event_type == EventType.SUSPECTED_DRAIN, Event.volume_l),
                            else_=0.0,
                        )
                    ),
                    0.0,
                ).cast(Float),
            )
            .where(Event.generator_id == generator_id, Event.occurred_at >= since)
            .group_by(event_day)
            .order_by(event_day)
        )
    ).all()

    events_by_day = {day: (refilled, drained) for day, refilled, drained in event_rows}

    daily: list[DailyConsumption] = []
    for day, consumed, runtime_hours in burn_rows:
        refilled, drained = events_by_day.pop(day, (0.0, 0.0))
        daily.append(
            DailyConsumption(
                day=day,
                consumed_l=round(float(consumed or 0.0), 2),
                runtime_hours=round(float(runtime_hours or 0.0), 2),
                refilled_l=round(float(refilled), 2),
                drained_l=round(abs(float(drained)), 2),
            )
        )

    # A day can carry a refill or a drain without a single reading — a unit
    # that was offline all day still gets fuelled. Those days would vanish if
    # the burn rollup were treated as the complete set of days.
    for day, (refilled, drained) in events_by_day.items():
        daily.append(
            DailyConsumption(
                day=day,
                consumed_l=0.0,
                runtime_hours=0.0,
                refilled_l=round(float(refilled), 2),
                drained_l=round(abs(float(drained)), 2),
            )
        )
    daily.sort(key=lambda entry: entry.day)

    return GeneratorConsumption(
        generator_id=generator.id,
        generator_name=generator.name,
        days=daily,
        total_consumed_l=round(sum(entry.consumed_l for entry in daily), 2),
        total_refilled_l=round(sum(entry.refilled_l for entry in daily), 2),
        total_drained_l=round(sum(entry.drained_l for entry in daily), 2),
    )
