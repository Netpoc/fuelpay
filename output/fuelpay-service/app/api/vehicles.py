"""Mobile machinery: tractors with an onboard tank, a yard and a field.

Read-only and tenant-scoped like the rest of the fleet API. Tractors are
created through `/v1/demo/tractors`.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.telemetry import BUCKET_LADDER, choose_bucket_minutes
from app.auth import require_organisation
from app.db import get_session
from app.models.entities import Organisation, Vehicle, VehicleReading
from app.schemas import (
    TrackSegment,
    VehicleDetail,
    VehicleOut,
    VehicleReadingOut,
    VehicleSeries,
    VehicleSeriesPoint,
    VehicleState,
    VehicleTodayStats,
    VehicleTrack,
)
from app.services.backfill import vehicle_spec
from app.simulation.field import field_polygon
from app.simulation.vehicle import OPERATIONS

router = APIRouter(prefix="/v1", tags=["vehicles"])

MAX_TRACK_POINTS = 2_000


async def _vehicle_or_404(
    session: AsyncSession, vehicle_id: uuid.UUID, organisation: Organisation
) -> Vehicle:
    vehicle = (
        await session.execute(
            select(Vehicle).where(
                Vehicle.id == vehicle_id, Vehicle.organisation_id == organisation.id
            )
        )
    ).scalar_one_or_none()
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found.")
    return vehicle


async def _latest(
    session: AsyncSession, organisation_id: uuid.UUID, vehicle_ids: list[uuid.UUID]
) -> dict[uuid.UUID, VehicleReading]:
    if not vehicle_ids:
        return {}
    # Bounded to the last day so DISTINCT ON scans a few thousand rows per
    # machine, not its whole history.
    since = datetime.now(UTC) - timedelta(days=1)
    rows = (
        await session.execute(
            select(VehicleReading)
            .where(
                VehicleReading.organisation_id == organisation_id,
                VehicleReading.vehicle_id.in_(vehicle_ids),
                VehicleReading.time >= since,
            )
            .distinct(VehicleReading.vehicle_id)
            .order_by(VehicleReading.vehicle_id, VehicleReading.time.desc())
        )
    ).scalars()
    return {row.vehicle_id: row for row in rows}


def _with_latest(vehicle: Vehicle, latest: VehicleReading | None) -> dict:
    return {
        **VehicleOut.model_validate(vehicle).model_dump(),
        "latest": VehicleReadingOut.model_validate(latest) if latest else None,
    }


@router.get("/vehicles", response_model=list[VehicleState], summary="List vehicles")
async def list_vehicles(
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> list[VehicleState]:
    vehicles = (
        (
            await session.execute(
                select(Vehicle)
                .where(Vehicle.organisation_id == organisation.id)
                .order_by(Vehicle.name)
            )
        )
        .scalars()
        .all()
    )
    latest = await _latest(session, organisation.id, [v.id for v in vehicles])
    return [VehicleState(**_with_latest(v, latest.get(v.id))) for v in vehicles]


@router.get("/vehicles/{vehicle_id}", response_model=VehicleDetail, summary="One vehicle")
async def get_vehicle(
    vehicle_id: uuid.UUID,
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> VehicleDetail:
    vehicle = await _vehicle_or_404(session, vehicle_id, organisation)
    latest = (await _latest(session, organisation.id, [vehicle.id])).get(vehicle.id)

    now = datetime.now(UTC)
    offset = timedelta(hours=vehicle.utc_offset_hours)
    local_midnight = (now + offset).replace(hour=0, minute=0, second=0, microsecond=0) - offset
    row = (
        await session.execute(
            select(
                cast(func.coalesce(func.max(VehicleReading.engine_hours), 0.0), Float),
                cast(func.coalesce(func.min(VehicleReading.engine_hours), 0.0), Float),
                cast(func.coalesce(func.sum(VehicleReading.distance_m), 0.0), Float),
                cast(func.coalesce(func.sum(VehicleReading.area_ha), 0.0), Float),
                cast(func.coalesce(func.sum(VehicleReading.consumed_l), 0.0), Float),
                cast(
                    func.coalesce(
                        func.sum(VehicleReading.consumed_l).filter(VehicleReading.area_ha > 0),
                        0.0,
                    ),
                    Float,
                ),
            ).where(
                VehicleReading.vehicle_id == vehicle.id,
                VehicleReading.organisation_id == organisation.id,
                VehicleReading.time >= local_midnight,
            )
        )
    ).one()
    hours_max, hours_min, distance_m, area, consumed, work_l = row
    quota = OPERATIONS[vehicle.primary_operation].quota_l_per_ha

    return VehicleDetail(
        **_with_latest(vehicle, latest),
        field_polygon=field_polygon(vehicle_spec(vehicle).field),
        today=VehicleTodayStats(
            engine_hours=round(hours_max - hours_min, 2),
            distance_km=round(distance_m / 1000, 2),
            area_ha=round(area, 2),
            consumed_l=round(consumed, 1),
            l_per_ha=round(work_l / area, 2) if area >= 0.5 else None,
            quota_l_per_ha=quota,
        ),
    )


@router.get(
    "/vehicles/{vehicle_id}/series",
    response_model=VehicleSeries,
    summary="Bucketed telemetry for charts",
)
async def vehicle_series(
    vehicle_id: uuid.UUID,
    hours: float = Query(default=24, gt=0, le=24 * 31),
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> VehicleSeries:
    """Means per bucket, except fuel level, which is the bucket's *minimum*: a
    siphon or a short fill is a step in the level, and averaging would round
    the corner off it."""
    await _vehicle_or_404(session, vehicle_id, organisation)
    bucket = choose_bucket_minutes(hours)
    assert bucket in BUCKET_LADDER
    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)
    seconds = bucket * 60
    bucket_start = func.to_timestamp(
        func.floor(func.extract("epoch", VehicleReading.time) / seconds) * seconds
    ).label("bucket")

    rows = (
        await session.execute(
            select(
                bucket_start,
                cast(func.min(VehicleReading.fuel_level_l), Float).label("fuel"),
                cast(func.avg(VehicleReading.fuel_rate_lph), Float).label("rate"),
                cast(func.avg(VehicleReading.rpm), Float).label("rpm"),
                cast(func.avg(VehicleReading.speed_kmh), Float).label("speed"),
                cast(func.max(VehicleReading.coolant_c), Float).label("coolant"),
                cast(func.avg(VehicleReading.oil_kpa), Float).label("oil"),
                cast(func.coalesce(func.sum(VehicleReading.consumed_l), 0.0), Float).label("used"),
                cast(func.coalesce(func.sum(VehicleReading.area_ha), 0.0), Float).label("area"),
            )
            .where(
                VehicleReading.vehicle_id == vehicle_id,
                VehicleReading.organisation_id == organisation.id,
                VehicleReading.time >= start,
                VehicleReading.time < end,
            )
            .group_by(bucket_start)
            .order_by(bucket_start)
        )
    ).all()

    def r(value: float | None, digits: int = 1) -> float | None:
        return None if value is None else round(value, digits)

    return VehicleSeries(
        vehicle_id=vehicle_id,
        bucket_minutes=bucket,
        start=start,
        end=end,
        points=[
            VehicleSeriesPoint(
                time=row.bucket,
                fuel_level_l=r(row.fuel),
                fuel_rate_lph=r(row.rate),
                rpm=r(row.rpm, 0),
                speed_kmh=r(row.speed),
                coolant_c=r(row.coolant),
                oil_kpa=r(row.oil, 0),
                consumed_l=round(row.used, 2),
                area_ha=round(row.area, 3),
            )
            for row in rows
        ],
    )


@router.get(
    "/vehicles/{vehicle_id}/track",
    response_model=VehicleTrack,
    summary="GPS track, split into segments by operation",
)
async def vehicle_track(
    vehicle_id: uuid.UUID,
    hours: float = Query(default=24, gt=0, le=24 * 7),
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> VehicleTrack:
    """Moving samples only (a parked machine draws nothing), thinned evenly to
    at most 2000 points. Consecutive samples with the same operation form one
    segment; each segment starts at the previous one's last point so the line
    is continuous on the map."""
    await _vehicle_or_404(session, vehicle_id, organisation)
    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)
    rows = (
        await session.execute(
            select(VehicleReading.latitude, VehicleReading.longitude, VehicleReading.operation)
            .where(
                VehicleReading.vehicle_id == vehicle_id,
                VehicleReading.organisation_id == organisation.id,
                VehicleReading.time >= start,
                VehicleReading.speed_kmh > 0.5,
            )
            .order_by(VehicleReading.time)
        )
    ).all()

    stride = max(1, -(-len(rows) // MAX_TRACK_POINTS))
    thinned = rows[::stride]
    segments: list[TrackSegment] = []
    for lat, lon, operation in thinned:
        point = (round(lon, 6), round(lat, 6))
        if segments and segments[-1].operation == operation:
            segments[-1].coordinates.append(point)
        else:
            joined = [segments[-1].coordinates[-1]] if segments else []
            segments.append(TrackSegment(operation=operation, coordinates=[*joined, point]))

    return VehicleTrack(
        vehicle_id=vehicle_id, start=start, end=end, points=len(thinned), segments=segments
    )
