"""Reading endpoints — the raw time-series.

Pagination is keyset, not OFFSET: readings are append-heavy and a client
walking backwards through a month of history would otherwise make the database
scan and discard everything it had already returned.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Boolean, Float, Integer, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_organisation
from app.db import get_session
from app.models.entities import Generator, Organisation, Reading
from app.schemas import GeneratorSeries, ReadingOut, ReadingPage, SeriesPoint

router = APIRouter(prefix="/v1", tags=["telemetry"])

DEFAULT_LIMIT = 500
MAX_LIMIT = 5_000

# Buckets a chart may ask for. Snapping to this ladder rather than accepting an
# arbitrary minute count keeps bucket edges aligned across requests, so panning
# a chart does not reshuffle every bar.
BUCKET_LADDER = (1, 5, 15, 30, 60, 120, 180, 360, 720, 1440)
DEFAULT_TARGET_POINTS = 600


async def _assert_generator_visible(
    session: AsyncSession, organisation_id: uuid.UUID, generator_id: uuid.UUID
) -> None:
    """404 for both 'does not exist' and 'belongs to another tenant'."""
    found = (
        await session.execute(
            select(Generator.id).where(
                Generator.id == generator_id,
                Generator.organisation_id == organisation_id,
            )
        )
    ).scalar_one_or_none()

    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generator not found.")


def choose_bucket_minutes(hours: float, target_points: int = DEFAULT_TARGET_POINTS) -> int:
    """Smallest ladder bucket that keeps a window under `target_points`. Pure.

    Sixty days at the 5-minute native resolution is 17,280 readings for one
    generator — over the endpoint's row cap and far more than a chart can draw.
    Choosing server-side means the client asks for a time span, not a
    resolution, and never has to know the cap exists.
    """
    if hours <= 0:
        return BUCKET_LADDER[0]
    needed = (hours * 60.0) / max(1, target_points)
    for bucket in BUCKET_LADDER:
        if bucket >= needed:
            return bucket
    return BUCKET_LADDER[-1]


@router.get(
    "/generators/{generator_id}/series",
    response_model=GeneratorSeries,
    summary="Downsampled reading series for charting, oldest first",
)
async def generator_series(
    generator_id: uuid.UUID,
    hours: float = Query(default=24, gt=0, le=24 * 400, description="Window ending now."),
    bucket_minutes: int | None = Query(
        default=None,
        ge=1,
        le=1440,
        description="Override the automatic bucket. Snapped to a fixed ladder.",
    ),
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> GeneratorSeries:
    """Aggregate a window into evenly spaced buckets.

    `fuel_min_l` is carried alongside the mean deliberately. A siphon takes
    10-30 minutes; inside a two-hour bucket the mean barely dips, and a chart
    drawn from means alone would hide the very incident it exists to show.
    Plotting the minimum preserves the cliff at any resolution.

    Buckets are computed by epoch arithmetic rather than Timescale's
    `time_bucket`, matching the choice in app/api/analytics.py that keeps these
    endpoints working on stock PostgreSQL.
    """
    await _assert_generator_visible(session, organisation.id, generator_id)

    bucket = bucket_minutes or choose_bucket_minutes(hours)
    if bucket_minutes is not None:
        # Snap an explicit request onto the ladder too, so bucket edges stay
        # aligned however the client asked.
        bucket = min(BUCKET_LADDER, key=lambda step: (abs(step - bucket_minutes), step))

    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)
    seconds = bucket * 60

    bucket_start = func.to_timestamp(
        func.floor(func.extract("epoch", Reading.time) / seconds) * seconds
    ).label("bucket")

    query = (
        select(
            bucket_start,
            cast(func.avg(Reading.fuel_level_l), Float).label("level"),
            cast(func.min(Reading.fuel_level_l), Float).label("level_min"),
            cast(func.max(Reading.fuel_level_l), Float).label("level_max"),
            cast(func.avg(Reading.load_kw), Float).label("load"),
            cast(func.coalesce(func.sum(Reading.consumed_l), 0.0), Float).label("consumed"),
            cast(func.bool_or(Reading.engine_running), Boolean).label("running"),
            cast(func.count(), Integer).label("samples"),
        )
        .where(
            Reading.generator_id == generator_id,
            Reading.organisation_id == organisation.id,
            Reading.time >= start,
            Reading.time < end,
        )
        .group_by(bucket_start)
        .order_by(bucket_start)
    )

    rows = (await session.execute(query)).all()

    return GeneratorSeries(
        generator_id=generator_id,
        bucket_minutes=bucket,
        start=start,
        end=end,
        points=[
            SeriesPoint(
                time=row.bucket,
                fuel_level_l=round(row.level, 2),
                fuel_min_l=round(row.level_min, 2),
                fuel_max_l=round(row.level_max, 2),
                load_kw=round(row.load, 3),
                consumed_l=round(row.consumed, 3),
                engine_running=bool(row.running),
                samples=row.samples,
            )
            for row in rows
        ],
    )


@router.get(
    "/generators/{generator_id}/readings",
    response_model=ReadingPage,
    summary="Time-series readings for one generator, newest first",
)
async def list_readings(
    generator_id: uuid.UUID,
    start: datetime | None = Query(default=None, description="Inclusive lower bound on time."),
    end: datetime | None = Query(default=None, description="Exclusive upper bound on time."),
    before: datetime | None = Query(
        default=None, description="Keyset cursor: return readings strictly older than this."
    ),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> ReadingPage:
    await _assert_generator_visible(session, organisation.id, generator_id)

    query = select(Reading).where(
        Reading.generator_id == generator_id,
        Reading.organisation_id == organisation.id,
    )
    if start is not None:
        query = query.where(Reading.time >= start)
    if end is not None:
        query = query.where(Reading.time < end)
    if before is not None:
        query = query.where(Reading.time < before)

    # Fetch one extra row to learn whether another page exists without a
    # second COUNT query over the hypertable.
    rows = list(
        (await session.execute(query.order_by(Reading.time.desc()).limit(limit + 1)))
        .scalars()
        .all()
    )

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = page[-1].time if has_more and page else None

    return ReadingPage(
        items=[ReadingOut.model_validate(row) for row in page],
        next_cursor=next_cursor,
    )


@router.get(
    "/readings/latest",
    response_model=list[ReadingOut],
    summary="Most recent reading for every generator in the fleet",
)
async def latest_readings(
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> list[Reading]:
    """One row per generator — the query behind a live fleet map or table.

    DISTINCT ON is PostgreSQL-specific but is by far the cheapest way to ask
    this: it walks the (generator_id, time) index and stops at the first row of
    each group instead of ranking every row in a window function.
    """
    query = (
        select(Reading)
        .where(Reading.organisation_id == organisation.id)
        .distinct(Reading.generator_id)
        .order_by(Reading.generator_id, Reading.time.desc())
    )
    result = await session.execute(query)
    return list(result.scalars().all())
