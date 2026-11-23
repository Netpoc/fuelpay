"""Tank endpoints: both storage tiers and their sensor connectivity.

Every query filters on the authenticated organisation. A caller who guesses
another tenant's tank UUID gets a 404, not their data.

The recurring idea here is that a level is only ever *measured*. Where a sensor
has not reported, the response says so — `sensor_status` plus a null level —
rather than carrying forward the last known value or interpolating. A stale
number rendered as current is worse than an obvious gap in a product whose job
is noticing that fuel moved.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Float, Integer, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_organisation
from app.db import get_session
from app.models.entities import (
    Event,
    EventType,
    Generator,
    GeneratorStatus,
    Organisation,
    Reading,
    SensorStatus,
    Site,
    Tank,
    TankKind,
    TankReading,
)
from app.schemas import (
    DailyTankFlow,
    SiteFuel,
    SiteOut,
    SiteSummary,
    TankConsumption,
    TankOut,
    TankSeries,
    TankSeriesPoint,
    TankState,
)

router = APIRouter(prefix="/v1", tags=["tanks"])

# How long a sensor may go quiet before it stops counting as live. The
# simulator emits every 5 simulated minutes, so a tank that has said nothing
# for a quarter of an hour has missed samples, and one silent for an hour has
# stopped in any sense that matters operationally.
STALE_AFTER_SECONDS = 15 * 60
OFFLINE_AFTER_SECONDS = 60 * 60

# Bucket ladder shared with the generator series so both charts snap to the
# same edges and can be overlaid without resampling.
BUCKET_LADDER: tuple[int, ...] = (1, 5, 15, 30, 60, 120, 360, 720, 1440)
TARGET_POINTS = 240


def choose_bucket_minutes(hours: float) -> int:
    needed = (hours * 60) / TARGET_POINTS
    for bucket in BUCKET_LADDER:
        if bucket >= needed:
            return bucket
    return BUCKET_LADDER[-1]


def sensor_status(measured_at: datetime | None, now: datetime) -> tuple[SensorStatus, float | None]:
    """Classify connectivity from the age of the newest reading.

    A tank that has never reported is OFFLINE rather than unknown: the sensor
    exists by definition, so silence is a fault, not an absence of hardware.
    """
    if measured_at is None:
        return SensorStatus.OFFLINE, None

    age = (now - measured_at).total_seconds()
    if age >= OFFLINE_AFTER_SECONDS:
        return SensorStatus.OFFLINE, age
    if age >= STALE_AFTER_SECONDS:
        return SensorStatus.STALE, age
    return SensorStatus.ONLINE, age


async def _latest_levels(
    session: AsyncSession,
    organisation_id: uuid.UUID,
    tank_ids: list[uuid.UUID],
) -> dict[uuid.UUID, tuple[datetime, float]]:
    """Newest reading per tank, as {tank_id: (time, level_l)}.

    DISTINCT ON walks each tank's index backwards and stops at the first row,
    which is why this stays cheap as the hypertable grows — unlike a
    GROUP BY MAX(time) that would scan every partition.
    """
    if not tank_ids:
        return {}

    query = (
        select(TankReading.tank_id, TankReading.time, TankReading.level_l)
        .where(
            TankReading.tank_id.in_(tank_ids),
            TankReading.organisation_id == organisation_id,
        )
        .distinct(TankReading.tank_id)
        .order_by(TankReading.tank_id, TankReading.time.desc())
    )
    rows = (await session.execute(query)).all()
    return {row.tank_id: (row.time, row.level_l) for row in rows}


def _to_state(tank: Tank, latest: tuple[datetime, float] | None, now: datetime) -> TankState:
    measured_at = latest[0] if latest else None
    level = latest[1] if latest else None
    state, age = sensor_status(measured_at, now)

    return TankState(
        **TankOut.model_validate(tank).model_dump(),
        sensor_status=state,
        level_l=round(level, 2) if level is not None else None,
        level_pct=(
            round((level / tank.capacity_l) * 100.0, 2)
            if level is not None and tank.capacity_l
            else None
        ),
        measured_at=measured_at,
        stale_seconds=round(age, 1) if age is not None else None,
    )


@router.get("/tanks", response_model=list[TankState], summary="List tanks with live levels")
async def list_tanks(
    site_id: uuid.UUID | None = Query(default=None, description="Filter to one site."),
    generator_id: uuid.UUID | None = Query(
        default=None, description="Filter to one generator's day tank."
    ),
    kind: TankKind | None = Query(default=None, description="Filter to BULK or DAY."),
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> list[TankState]:
    query = select(Tank).where(Tank.organisation_id == organisation.id)
    if site_id is not None:
        query = query.where(Tank.site_id == site_id)
    if generator_id is not None:
        query = query.where(Tank.generator_id == generator_id)
    if kind is not None:
        query = query.where(Tank.kind == kind)

    # BULK first, then by name: a site's shared storage is the context for the
    # day tanks that draw on it, so it reads better above them.
    tanks = list((await session.execute(query.order_by(Tank.kind, Tank.name))).scalars().all())

    now = datetime.now(UTC)
    levels = await _latest_levels(session, organisation.id, [tank.id for tank in tanks])
    return [_to_state(tank, levels.get(tank.id), now) for tank in tanks]


@router.get(
    "/sites/{site_id}/fuel",
    response_model=SiteFuel,
    summary="Both storage tiers for one site",
)
async def site_fuel(
    site_id: uuid.UUID,
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> SiteFuel:
    """The site's bulk reserve alongside the day tanks it feeds.

    The bulk total is summed over *reporting* tanks only, and the response says
    how many of the site's tanks that was. A total quietly computed over a
    partial set would read as the site holding less fuel than it does, which
    is exactly the kind of wrong number that triggers a pointless callout.
    """
    site = (
        await session.execute(
            select(Site).where(Site.id == site_id, Site.organisation_id == organisation.id)
        )
    ).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found.")

    tanks = list(
        (
            await session.execute(
                select(Tank).where(Tank.site_id == site_id).order_by(Tank.kind, Tank.name)
            )
        )
        .scalars()
        .all()
    )

    now = datetime.now(UTC)
    levels = await _latest_levels(session, organisation.id, [tank.id for tank in tanks])
    states = [_to_state(tank, levels.get(tank.id), now) for tank in tanks]

    bulk = [state for state in states if state.kind is TankKind.BULK]
    day = [state for state in states if state.kind is TankKind.DAY]

    reporting = [state for state in bulk if state.level_l is not None]
    bulk_capacity = sum(state.capacity_l for state in bulk)
    bulk_level = sum(state.level_l or 0.0 for state in reporting) if reporting else None

    return SiteFuel(
        site=SiteOut.model_validate(site),
        bulk=bulk,
        day=day,
        bulk_capacity_l=round(bulk_capacity, 2),
        bulk_level_l=round(bulk_level, 2) if bulk_level is not None else None,
        bulk_level_pct=(
            round((bulk_level / bulk_capacity) * 100.0, 2)
            if bulk_level is not None and bulk_capacity
            else None
        ),
        bulk_tanks_reporting=len(reporting),
        bulk_tanks_total=len(bulk),
    )


class _Tier(NamedTuple):
    capacity_l: float
    level_l: float | None
    level_pct: float | None
    reporting: int
    total: int
    threshold: float


def _tier_rollup(states: list[TankState]) -> _Tier:
    """Roll one storage tier up to the numbers a map pin needs.

    Levels sum over reporting tanks only; the counts say how many that was. The
    threshold is the strictest across the tier, which is the safe read when
    tanks on one site disagree.
    """
    reporting = [state for state in states if state.level_l is not None]
    capacity = sum(state.capacity_l for state in states)
    level = sum(state.level_l or 0.0 for state in reporting) if reporting else None

    return _Tier(
        capacity_l=round(capacity, 2),
        level_l=round(level, 2) if level is not None else None,
        level_pct=(
            round((level / capacity) * 100.0, 2) if level is not None and capacity else None
        ),
        reporting=len(reporting),
        total=len(states),
        threshold=max((state.reorder_threshold_pct for state in states), default=0.0),
    )


# Fuel arriving (DELIVERY into bulk, REFILL into a generator's tank) versus fuel
# leaving unaccounted. TRANSFER is deliberately absent: bulk -> day is fuel
# moving *within* the site, and counting it as arrival would double it.
_ARRIVING = (EventType.DELIVERY, EventType.REFILL)
_LEAVING = (
    EventType.SUSPECTED_DRAIN,
    EventType.SHORT_DELIVERY,
    EventType.UNVERIFIED_LOSS,
)


# Registered above `/sites/{site_id}/fuel`, but the two cannot collide anyway —
# one segment versus three. If a bare `/sites/{site_id}` is ever added, this
# literal route MUST stay ahead of it or Starlette will try to parse "summary"
# as a UUID and answer 422.
@router.get(
    "/sites/summary",
    response_model=list[SiteSummary],
    summary="Every site rolled up to one row, for a fleet map",
)
async def sites_summary(
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> list[SiteSummary]:
    """Both tiers, generator posture and 24-hour movement, per site.

    One request backs a whole map. The per-site alternative is N round-trips to
    `/sites/{id}/fuel`, which still would not carry consumption — nothing else
    in the API aggregates burn by site.

    Cross-referencing in Python mirrors `/summary` and is fine at demo-fleet
    scale; at thousands of sites the rollups belong in SQL.
    """
    now = datetime.now(UTC)
    since = now - timedelta(hours=24)

    sites = list(
        (
            await session.execute(
                select(Site).where(Site.organisation_id == organisation.id).order_by(Site.name)
            )
        )
        .scalars()
        .all()
    )
    if not sites:
        return []

    tanks = list(
        (
            await session.execute(
                select(Tank)
                .where(Tank.organisation_id == organisation.id)
                .order_by(Tank.kind, Tank.name)
            )
        )
        .scalars()
        .all()
    )
    levels = await _latest_levels(session, organisation.id, [tank.id for tank in tanks])
    states = [_to_state(tank, levels.get(tank.id), now) for tank in tanks]

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
    site_of_generator = {generator.id: generator.site_id for generator in generators}
    site_of_tank = {tank.id: tank.site_id for tank in tanks}

    running = (
        await session.execute(
            select(Reading.generator_id, Reading.engine_running)
            .where(Reading.organisation_id == organisation.id)
            .distinct(Reading.generator_id)
            .order_by(Reading.generator_id, Reading.time.desc())
        )
    ).all()
    engine_on = {row.generator_id for row in running if row.engine_running}

    burn_rows = (
        await session.execute(
            select(
                Generator.site_id,
                cast(func.coalesce(func.sum(Reading.consumed_l), 0.0), Float),
            )
            .join(Reading, Reading.generator_id == Generator.id)
            .where(Generator.organisation_id == organisation.id, Reading.time >= since)
            .group_by(Generator.site_id)
        )
    ).all()
    burn_by_site = {site_id: float(consumed) for site_id, consumed in burn_rows}

    # An event belongs to a site through its tank, or failing that its
    # generator: a delivery into shared bulk storage carries no generator at
    # all, so resolving generator-first would drop exactly the tanker calls a
    # map most needs to show.
    movements = (
        await session.execute(
            select(Event.tank_id, Event.generator_id, Event.event_type, Event.volume_l).where(
                Event.organisation_id == organisation.id,
                Event.occurred_at >= since,
                Event.event_type.in_(_ARRIVING + _LEAVING),
            )
        )
    ).all()

    moved: dict[EventType, dict[uuid.UUID, float]] = {
        event_type: {} for event_type in _ARRIVING + _LEAVING
    }
    for tank_id, generator_id, event_type, volume in movements:
        site_id = site_of_tank.get(tank_id) or site_of_generator.get(generator_id)
        if site_id is None or volume is None:
            continue
        bucket = moved[event_type]
        # Losses are stored negative; report the magnitude that moved.
        bucket[site_id] = bucket.get(site_id, 0.0) + abs(float(volume))

    def _moved(site_id: uuid.UUID, *types: EventType) -> float:
        return round(sum(moved[event_type].get(site_id, 0.0) for event_type in types), 2)

    summaries: list[SiteSummary] = []
    for site in sites:
        site_states = [state for state in states if state.site_id == site.id]
        bulk = _tier_rollup([state for state in site_states if state.kind is TankKind.BULK])
        day = _tier_rollup([state for state in site_states if state.kind is TankKind.DAY])
        site_generators = [generator for generator in generators if generator.site_id == site.id]

        summaries.append(
            SiteSummary(
                site=SiteOut.model_validate(site),
                generator_count=len(site_generators),
                running_count=sum(1 for g in site_generators if g.id in engine_on),
                bulk_capacity_l=bulk.capacity_l,
                bulk_level_l=bulk.level_l,
                bulk_level_pct=bulk.level_pct,
                bulk_tanks_reporting=bulk.reporting,
                bulk_tanks_total=bulk.total,
                bulk_reorder_threshold_pct=bulk.threshold,
                day_capacity_l=day.capacity_l,
                day_level_l=day.level_l,
                day_level_pct=day.level_pct,
                day_tanks_reporting=day.reporting,
                day_tanks_total=day.total,
                day_reorder_threshold_pct=day.threshold,
                dark_sensors=sum(
                    1 for state in site_states if state.sensor_status is SensorStatus.OFFLINE
                ),
                consumed_l_24h=round(burn_by_site.get(site.id, 0.0), 2),
                delivered_l_24h=_moved(site.id, *_ARRIVING),
                drained_l_24h=_moved(site.id, EventType.SUSPECTED_DRAIN),
                short_delivery_l_24h=_moved(site.id, EventType.SHORT_DELIVERY),
                unverified_loss_l_24h=_moved(site.id, EventType.UNVERIFIED_LOSS),
                as_of=now,
            )
        )

    return summaries


@router.get(
    "/tanks/{tank_id}/consumption",
    response_model=TankConsumption,
    summary="Daily fuel movement through one tank",
)
async def tank_consumption(
    tank_id: uuid.UUID,
    days: int = Query(default=30, ge=1, le=365, description="Days of history to roll up."),
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> TankConsumption:
    """Roll a tank's movements up by day, split by cause.

    Every figure is a SUM of recorded movements, not a level delta. A delta
    would net a delivery against the burn that followed it inside the same day
    and report neither honestly — the whole reason `consumed_l` and
    `transferred_l` are stored per reading.

    `samples` rides along so a partly-unobserved day is visible as such. A tank
    whose sensor was dark for eighteen hours still reports whatever it saw, and
    without the count that reads as a genuinely quiet day.
    """
    tank = (
        await session.execute(
            select(Tank).where(Tank.id == tank_id, Tank.organisation_id == organisation.id)
        )
    ).scalar_one_or_none()
    if tank is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tank not found.")

    # Align the window to midnight UTC rather than starting `days` ago to the
    # second. Otherwise the oldest bucket is a part-day that still gets labelled
    # as a whole one: its `samples` come out around 40% and read as a sensor
    # that missed half a day, when the query simply did not ask for it. Every
    # returned day is now complete except today, which is partial by definition.
    now = datetime.now(UTC)
    since = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)

    reading_day = func.date_trunc("day", TankReading.time).label("day")
    flow_rows = (
        await session.execute(
            select(
                reading_day,
                cast(func.coalesce(func.sum(TankReading.consumed_l), 0.0), Float),
                cast(func.coalesce(func.sum(TankReading.transferred_l), 0.0), Float),
                cast(func.count(), Integer),
            )
            .where(TankReading.tank_id == tank_id, TankReading.time >= since)
            .group_by(reading_day)
            .order_by(reading_day)
        )
    ).all()

    def _sum_of(event_type: EventType):
        return cast(
            func.coalesce(
                func.sum(case((Event.event_type == event_type, Event.volume_l), else_=0.0)), 0.0
            ),
            Float,
        )

    event_day = func.date_trunc("day", Event.occurred_at).label("day")
    event_rows = (
        await session.execute(
            select(
                event_day,
                _sum_of(EventType.DELIVERY),
                _sum_of(EventType.SUSPECTED_DRAIN),
                _sum_of(EventType.UNVERIFIED_LOSS),
            )
            .where(Event.tank_id == tank_id, Event.occurred_at >= since)
            .group_by(event_day)
            .order_by(event_day)
        )
    ).all()
    events_by_day = {
        day: (delivered, drained, unverified) for day, delivered, drained, unverified in event_rows
    }

    daily: list[DailyTankFlow] = []
    for day, consumed, transferred, samples in flow_rows:
        delivered, drained, unverified = events_by_day.pop(day, (0.0, 0.0, 0.0))
        daily.append(
            DailyTankFlow(
                day=day,
                consumed_l=round(float(consumed), 2),
                transferred_l=round(float(transferred), 2),
                delivered_l=round(float(delivered), 2),
                drained_l=round(abs(float(drained)), 2),
                unverified_loss_l=round(abs(float(unverified)), 2),
                samples=int(samples),
            )
        )

    # A day can carry a delivery with no readings at all — a tanker still calls
    # at a site whose sensor is dark. Those days would vanish entirely if the
    # reading rollup were treated as the complete set of days, which is exactly
    # the day you would most want to see.
    for day, (delivered, drained, unverified) in events_by_day.items():
        daily.append(
            DailyTankFlow(
                day=day,
                consumed_l=0.0,
                transferred_l=0.0,
                delivered_l=round(float(delivered), 2),
                drained_l=round(abs(float(drained)), 2),
                unverified_loss_l=round(abs(float(unverified)), 2),
                samples=0,
            )
        )
    daily.sort(key=lambda entry: entry.day)

    return TankConsumption(
        tank_id=tank.id,
        tank_name=tank.name,
        kind=tank.kind,
        capacity_l=tank.capacity_l,
        days=daily,
        total_consumed_l=round(sum(entry.consumed_l for entry in daily), 2),
        total_transferred_l=round(sum(entry.transferred_l for entry in daily), 2),
        total_delivered_l=round(sum(entry.delivered_l for entry in daily), 2),
        total_drained_l=round(sum(entry.drained_l for entry in daily), 2),
        total_unverified_loss_l=round(sum(entry.unverified_loss_l for entry in daily), 2),
    )


@router.get(
    "/tanks/{tank_id}/series",
    response_model=TankSeries,
    summary="Downsampled level series for one tank, oldest first",
)
async def tank_series(
    tank_id: uuid.UUID,
    hours: float = Query(default=24, gt=0, le=24 * 400, description="Window ending now."),
    bucket_minutes: int | None = Query(
        default=None,
        ge=1,
        le=1440,
        description="Override the automatic bucket. Snapped to a fixed ladder.",
    ),
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> TankSeries:
    """Aggregate a window into evenly spaced buckets.

    `level_min_l` is carried alongside the mean deliberately. A siphon takes
    10-30 minutes; inside a two-hour bucket the mean barely dips, and a chart
    drawn from means alone would hide the very incident it exists to show.

    Empty buckets are absent from `points` rather than zero-filled. A caller
    plotting this must break the line across a gap: joining two levels either
    side of an outage draws a straight line through the exact window in which
    fuel is most likely to have been taken.
    """
    tank = (
        await session.execute(
            select(Tank).where(Tank.id == tank_id, Tank.organisation_id == organisation.id)
        )
    ).scalar_one_or_none()
    if tank is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tank not found.")

    bucket = bucket_minutes or choose_bucket_minutes(hours)
    if bucket_minutes is not None:
        bucket = min(BUCKET_LADDER, key=lambda step: (abs(step - bucket_minutes), step))

    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)
    seconds = bucket * 60

    bucket_start = func.to_timestamp(
        func.floor(func.extract("epoch", TankReading.time) / seconds) * seconds
    ).label("bucket")

    query = (
        select(
            bucket_start,
            cast(func.avg(TankReading.level_l), Float).label("level"),
            cast(func.min(TankReading.level_l), Float).label("level_min"),
            cast(func.max(TankReading.level_l), Float).label("level_max"),
            cast(func.coalesce(func.sum(TankReading.consumed_l), 0.0), Float).label("consumed"),
            cast(func.coalesce(func.sum(TankReading.transferred_l), 0.0), Float).label(
                "transferred"
            ),
            cast(func.count(), Integer).label("samples"),
        )
        .where(
            TankReading.tank_id == tank_id,
            TankReading.organisation_id == organisation.id,
            TankReading.time >= start,
            TankReading.time < end,
        )
        .group_by(bucket_start)
        .order_by(bucket_start)
    )

    rows = (await session.execute(query)).all()

    return TankSeries(
        tank_id=tank_id,
        kind=tank.kind,
        capacity_l=tank.capacity_l,
        bucket_minutes=bucket,
        start=start,
        end=end,
        points=[
            TankSeriesPoint(
                time=row.bucket,
                level_l=round(row.level, 2),
                level_min_l=round(row.level_min, 2),
                level_max_l=round(row.level_max, 2),
                consumed_l=round(row.consumed, 3),
                transferred_l=round(row.transferred, 3),
                samples=row.samples,
            )
            for row in rows
        ],
    )
