"""Simulator and system health, plus the controls to nudge them."""

import shutil
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_schemas import (
    BackfillItem,
    SystemStatus,
    TableSize,
    TickSummary,
    TuningOut,
    TuningUpdate,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.models.entities import (
    Generator,
    Organisation,
    SimulationState,
    SimulationStatus,
    Site,
    Vehicle,
    VehicleSimulationState,
)
from app.services import ticker
from app.services.admin_auth import AdminActor, audit, require_owner, require_platform_admin
from app.services.demo_jobs import expire_demos, retry_backfill
from app.services.platform_settings import (
    effective_tuning,
    load_overrides,
    save_overrides,
    validate_tuning,
)
from app.tuning import DEFAULT_VEHICLE

router = APIRouter()

NOT_LIVE = (SimulationStatus.PENDING, SimulationStatus.BACKFILLING, SimulationStatus.FAILED)


def _tick_summary(report: "ticker.TickReport | None") -> TickSummary | None:
    if report is None:
        return None
    return TickSummary(
        started_at=report.started_at,
        sites=report.sites,
        generators=report.generators,
        vehicles=report.vehicles,
        readings=report.readings,
        vehicle_readings=report.vehicle_readings,
        events=report.events,
        skipped_locked=report.skipped_locked,
    )


@router.get("/system", response_model=SystemStatus, summary="Simulator and system health")
async def system_status(
    _: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SystemStatus:
    now = datetime.now(UTC)
    # Only tenants the ticker still advances: an expired demo stops ticking by
    # design and would otherwise read as an ever-growing lag until purged.
    active = or_(Organisation.is_demo.is_(False), Organisation.demo_expires_at > now)
    oldest = []
    for query in (
        select(func.min(SimulationState.simulated_at))
        .join(Generator, Generator.id == SimulationState.generator_id)
        .join(Organisation, Organisation.id == Generator.organisation_id)
        .where(active),
        select(func.min(VehicleSimulationState.simulated_at))
        .join(Vehicle, Vehicle.id == VehicleSimulationState.vehicle_id)
        .join(Organisation, Organisation.id == Vehicle.organisation_id)
        .where(active),
    ):
        value = (await session.execute(query)).scalar_one()
        if value is not None:
            oldest.append(value)
    lag = round((now - min(oldest)).total_seconds(), 1) if oldest else None

    backfills: list[BackfillItem] = []
    for kind, model in (("location", Site), ("tractor", Vehicle)):
        rows = (
            await session.execute(
                select(model, Organisation.name)
                .join(Organisation, Organisation.id == model.organisation_id)
                .where(model.simulation_status.in_(NOT_LIVE))
                .order_by(model.created_at.desc())
            )
        ).all()
        backfills += [
            BackfillItem(
                kind=kind,
                id=row.id,
                name=row.name,
                organisation=org_name,
                simulation_status=row.simulation_status,
                progress=row.backfill_progress,
                error=row.backfill_error,
            )
            for row, org_name in rows
        ]

    db_bytes = (
        await session.execute(text("SELECT pg_database_size(current_database())"))
    ).scalar_one()
    tables = (
        await session.execute(
            text(
                "SELECT relname, pg_total_relation_size(relid) AS bytes "
                "FROM pg_catalog.pg_statio_user_tables ORDER BY bytes DESC LIMIT 8"
            )
        )
    ).all()
    disk = shutil.disk_usage("/")

    return SystemStatus(
        sim_enabled=settings.sim_enabled,
        tick_seconds=settings.sim_tick_seconds,
        max_lag_seconds=lag,
        last_tick=_tick_summary(ticker.LAST_REPORT),
        backfills=backfills,
        database_bytes=int(db_bytes),
        tables=[TableSize(name=name, bytes=int(size)) for name, size in tables],
        disk_total_bytes=disk.total,
        disk_free_bytes=disk.free,
        as_of=now,
    )


@router.post(
    "/system/backfills/{kind}/{entity_id}/retry",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a failed or stuck backfill",
)
async def retry(
    kind: Literal["location", "tractor"],
    entity_id: uuid.UUID,
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    # Audited before the job commits, so the record lands in that commit.
    await audit(session, actor, "backfill.retry", kind, entity_id)
    if not await retry_backfill(session, kind, entity_id, settings):
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nothing to retry: not found or already live.",
        )
    return {"queued": True}


@router.post("/system/tick", response_model=TickSummary, summary="Run one simulator tick now")
async def tick_now(
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TickSummary:
    # Committed first: a tick that finds the lock taken rolls its session back,
    # and the request should stay on record either way.
    await audit(session, actor, "system.tick")
    await session.commit()
    report = await ticker.run_tick(session, settings)
    summary = _tick_summary(report)
    assert summary is not None
    return summary


@router.post("/system/expire-now", summary="Run the demo expiry job now")
async def expire_now(
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    await audit(session, actor, "system.expire")
    revoked, purged = await expire_demos(session, settings)
    return {"keys_revoked": revoked, "tenants_purged": purged}


@router.get("/settings/tuning", response_model=TuningOut, summary="Incident tuning")
async def get_tuning(
    _: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TuningOut:
    overrides = await load_overrides(session)
    return TuningOut(
        effective=effective_tuning(settings.theft_tuning, overrides),
        overrides=overrides,
        defaults={"theft": asdict(settings.theft_tuning), "vehicle": asdict(DEFAULT_VEHICLE)},
    )


@router.put("/settings/tuning", response_model=TuningOut, summary="Change incident tuning")
async def put_tuning(
    payload: TuningUpdate,
    actor: AdminActor = Depends(require_owner),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TuningOut:
    """Replaces the whole override set. Applies to every tenant from the next tick."""
    try:
        clean = validate_tuning(payload.overrides)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    before = await load_overrides(session)
    await save_overrides(session, clean, actor.label)
    await audit(
        session, actor, "tuning.update", "settings", "tuning", {"before": before, "after": clean}
    )
    return TuningOut(
        effective=effective_tuning(settings.theft_tuning, clean),
        overrides=clean,
        defaults={"theft": asdict(settings.theft_tuning), "vehicle": asdict(DEFAULT_VEHICLE)},
    )
