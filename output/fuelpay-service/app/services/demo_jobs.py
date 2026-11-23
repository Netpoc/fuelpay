"""Background work for demo accounts: history generation and expiry.

A prospect's new location or tractor is created PENDING and handed to
`enqueue_backfill`, which generates `demo_backfill_days` of history in the
background and flips it LIVE. Until then the live ticker ignores it, so the two
can never write the same entity at once and no tick lock is needed here.

History is generated in one-day chunks, each committed with a progress update,
so the signup wizard can show a moving bar and a crash loses at most a day.
The simulation itself is CPU-bound and runs in a worker thread to keep the
event loop serving requests; a semaphore caps how many run together.

`recover_interrupted` runs at startup: anything left BACKFILLING by a restart
has its partial rows removed and starts again from scratch, since events have
no natural key and could not be replayed safely over the top.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import get_sessionmaker
from app.models.entities import (
    ApiKey,
    Event,
    Generator,
    Organisation,
    Reading,
    SimulationStatus,
    Site,
    Tank,
    TankReading,
    Vehicle,
    VehicleReading,
)
from app.services.backfill import load_site_specs, load_vehicle_specs
from app.services.persistence import (
    insert_events,
    insert_readings,
    insert_tank_readings,
    insert_vehicle_readings,
    save_site_state,
    save_vehicle_state,
    touch_tank_last_seen,
)
from app.services.platform_settings import load_tuning
from app.simulation.engine import initial_site_state
from app.simulation.site import run_site_span
from app.simulation.vehicle import initial_vehicle_state, run_vehicle_span

logger = logging.getLogger(__name__)

EntityKind = Literal["location", "tractor"]
CHUNK = timedelta(days=1)

# Strong references: asyncio keeps only weak ones to tasks, and a job that is
# garbage-collected mid-flight simply vanishes.
_tasks: set[asyncio.Task] = set()
_semaphore: asyncio.Semaphore | None = None


def _gate(settings: Settings) -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max(1, settings.demo_backfill_concurrency))
    return _semaphore


def enqueue_backfill(kind: EntityKind, entity_id: uuid.UUID, settings: Settings) -> None:
    """Schedule history generation. Call only after the entity is committed."""
    job = _backfill_site if kind == "location" else _backfill_vehicle
    task = asyncio.create_task(job(entity_id, settings), name=f"backfill-{kind}-{entity_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _fail(model: type[Site] | type[Vehicle], entity_id: uuid.UUID, error: str) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(model)
            .where(model.id == entity_id)
            .values(simulation_status=SimulationStatus.FAILED, backfill_error=error[:500])
        )
        await session.commit()


async def _claim(
    session: AsyncSession, model: type[Site] | type[Vehicle], entity_id: uuid.UUID
) -> bool:
    """PENDING -> BACKFILLING, atomically. False if someone else has it."""
    result = await session.execute(
        update(model)
        .where(model.id == entity_id, model.simulation_status == SimulationStatus.PENDING)
        .values(simulation_status=SimulationStatus.BACKFILLING, backfill_progress=0.0)
    )
    await session.commit()
    return bool(result.rowcount)


async def _backfill_site(site_id: uuid.UUID, settings: Settings) -> None:
    async with _gate(settings):
        try:
            async with get_sessionmaker()() as session:
                if not await _claim(session, Site, site_id):
                    return
                specs = await load_site_specs(session, site_id=site_id, only_live=False)
                if not specs:
                    raise RuntimeError("Location has no generator with a day tank.")
                spec = specs[0]
                theft, _ = await load_tuning(session, settings)

                until = datetime.now(UTC)
                start = until - timedelta(days=settings.demo_backfill_days)
                state = initial_site_state(spec, start, settings.sim_seed)
                total = (until - start).total_seconds()

                while state.simulated_at < until:
                    chunk_end = min(state.simulated_at + CHUNK, until)
                    state, readings, tank_readings, events = await asyncio.to_thread(
                        run_site_span,
                        spec,
                        state,
                        chunk_end,
                        settings.sim_minutes_per_tick,
                        settings.sim_seed,
                        theft,
                        settings.refill_window,
                    )
                    await insert_readings(session, readings)
                    await insert_tank_readings(session, tank_readings)
                    await touch_tank_last_seen(session, tank_readings)
                    await insert_events(session, events)
                    progress = (state.simulated_at - start).total_seconds() / total
                    await session.execute(
                        update(Site)
                        .where(Site.id == site_id)
                        .values(backfill_progress=round(min(progress, 0.99), 3))
                    )
                    await session.commit()

                # State and the LIVE flip commit together, so the ticker picks
                # the site up exactly where the history ends.
                await save_site_state(session, spec, state)
                await session.execute(
                    update(Site)
                    .where(Site.id == site_id)
                    .values(simulation_status=SimulationStatus.LIVE, backfill_progress=1.0)
                )
                await session.commit()
                logger.info("demo location %s backfilled and live", site_id)
        except Exception as exc:
            logger.exception("backfill failed for location %s", site_id)
            await _fail(Site, site_id, str(exc) or exc.__class__.__name__)


async def _backfill_vehicle(vehicle_id: uuid.UUID, settings: Settings) -> None:
    async with _gate(settings):
        try:
            async with get_sessionmaker()() as session:
                if not await _claim(session, Vehicle, vehicle_id):
                    return
                specs = await load_vehicle_specs(session, vehicle_id=vehicle_id, only_live=False)
                if not specs:
                    raise RuntimeError("Vehicle not found.")
                spec = specs[0]
                _, vehicle_tuning = await load_tuning(session, settings)

                until = datetime.now(UTC)
                start = until - timedelta(days=settings.demo_backfill_days)
                state = initial_vehicle_state(spec, start, settings.sim_seed)
                total = (until - state.simulated_at).total_seconds()
                origin = state.simulated_at

                while state.simulated_at + timedelta(minutes=1) <= until:
                    chunk_end = min(state.simulated_at + CHUNK, until)
                    state, readings, events = await asyncio.to_thread(
                        run_vehicle_span, spec, state, chunk_end, settings.sim_seed, vehicle_tuning
                    )
                    await insert_vehicle_readings(session, readings)
                    await insert_events(session, events)
                    progress = (state.simulated_at - origin).total_seconds() / total
                    await session.execute(
                        update(Vehicle)
                        .where(Vehicle.id == vehicle_id)
                        .values(backfill_progress=round(min(progress, 0.99), 3))
                    )
                    await session.commit()

                await save_vehicle_state(session, vehicle_id, state)
                await session.execute(
                    update(Vehicle)
                    .where(Vehicle.id == vehicle_id)
                    .values(simulation_status=SimulationStatus.LIVE, backfill_progress=1.0)
                )
                await session.commit()
                logger.info("demo tractor %s backfilled and live", vehicle_id)
        except Exception as exc:
            logger.exception("backfill failed for tractor %s", vehicle_id)
            await _fail(Vehicle, vehicle_id, str(exc) or exc.__class__.__name__)


async def _discard_partial_site(session: AsyncSession, site_id: uuid.UUID) -> None:
    generator_ids = select(Generator.id).where(Generator.site_id == site_id)
    tank_ids = select(Tank.id).where(Tank.site_id == site_id)
    await session.execute(delete(Reading).where(Reading.generator_id.in_(generator_ids)))
    await session.execute(delete(TankReading).where(TankReading.tank_id.in_(tank_ids)))
    await session.execute(
        delete(Event).where(Event.generator_id.in_(generator_ids) | Event.tank_id.in_(tank_ids))
    )


async def retry_backfill(
    session: AsyncSession, kind: EntityKind, entity_id: uuid.UUID, settings: Settings
) -> bool:
    """Start a failed or stuck backfill again from scratch.

    Partial history is removed first: events have no natural key, so replaying
    over half-written rows would duplicate them. Commits, then enqueues.
    Returns False if the entity does not exist or is already LIVE.
    """
    model = Site if kind == "location" else Vehicle
    row = await session.get(model, entity_id)
    if row is None or row.simulation_status == SimulationStatus.LIVE:
        return False
    if kind == "location":
        await _discard_partial_site(session, entity_id)
    else:
        await session.execute(delete(VehicleReading).where(VehicleReading.vehicle_id == entity_id))
        await session.execute(delete(Event).where(Event.vehicle_id == entity_id))
    row.simulation_status = SimulationStatus.PENDING
    row.backfill_progress = 0.0
    row.backfill_error = None
    await session.commit()
    enqueue_backfill(kind, entity_id, settings)
    return True


async def recover_interrupted(settings: Settings) -> int:
    """Restart any backfill a shutdown interrupted, and any never started."""
    async with get_sessionmaker()() as session:
        stuck_sites = (
            await session.execute(
                select(Site.id, Site.simulation_status).where(
                    Site.simulation_status.in_(
                        (SimulationStatus.PENDING, SimulationStatus.BACKFILLING)
                    )
                )
            )
        ).all()
        stuck_vehicles = (
            await session.execute(
                select(Vehicle.id, Vehicle.simulation_status).where(
                    Vehicle.simulation_status.in_(
                        (SimulationStatus.PENDING, SimulationStatus.BACKFILLING)
                    )
                )
            )
        ).all()

        for site_id, status in stuck_sites:
            if status == SimulationStatus.BACKFILLING:
                await _discard_partial_site(session, site_id)
                await session.execute(
                    update(Site)
                    .where(Site.id == site_id)
                    .values(simulation_status=SimulationStatus.PENDING, backfill_progress=0.0)
                )
        for vehicle_id, status in stuck_vehicles:
            if status == SimulationStatus.BACKFILLING:
                await session.execute(
                    delete(VehicleReading).where(VehicleReading.vehicle_id == vehicle_id)
                )
                await session.execute(delete(Event).where(Event.vehicle_id == vehicle_id))
                await session.execute(
                    update(Vehicle)
                    .where(Vehicle.id == vehicle_id)
                    .values(simulation_status=SimulationStatus.PENDING, backfill_progress=0.0)
                )
        await session.commit()

    for site_id, _ in stuck_sites:
        enqueue_backfill("location", site_id, settings)
    for vehicle_id, _ in stuck_vehicles:
        enqueue_backfill("tractor", vehicle_id, settings)
    return len(stuck_sites) + len(stuck_vehicles)


# --- expiry ---------------------------------------------------------------

PURGE_BATCH = 20


async def expire_demos(
    session: AsyncSession, settings: Settings, now: datetime | None = None
) -> tuple[int, int]:
    """Revoke keys of expired demos, purge those past the grace period.

    Returns (keys revoked, organisations purged). Commits.

    Auth already refuses an expired demo's key; revoking it as well means the
    refusal survives an extension being granted by mistake to the wrong org.
    Purging deletes the organisation and, by cascade, everything it owns; the
    coupon redemption record stays, with its organisation set to NULL.
    """
    now = now or datetime.now(UTC)
    expired = select(Organisation.id).where(
        Organisation.is_demo.is_(True), Organisation.demo_expires_at <= now
    )
    revoked = await session.execute(
        update(ApiKey)
        .where(ApiKey.organisation_id.in_(expired), ApiKey.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    cutoff = now - timedelta(hours=settings.demo_purge_grace_hours)
    doomed = list(
        (
            await session.execute(
                select(Organisation.id)
                .where(Organisation.is_demo.is_(True), Organisation.demo_expires_at <= cutoff)
                .limit(PURGE_BATCH)
            )
        )
        .scalars()
        .all()
    )
    if doomed:
        await session.execute(delete(Organisation).where(Organisation.id.in_(doomed)))
    await session.commit()

    if revoked.rowcount or doomed:
        logger.info(
            "demo expiry: revoked %d key(s), purged %d organisation(s)",
            revoked.rowcount or 0,
            len(doomed),
        )
    return revoked.rowcount or 0, len(doomed)
