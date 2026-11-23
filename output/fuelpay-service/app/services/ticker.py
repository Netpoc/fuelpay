"""The live simulator.

Every tick, each active site is advanced from its persisted cursor up to
wall-clock time and its output written. Advancing *to now* rather than by a
fixed amount is what makes the ticker self-correcting: a slow tick, a paused
container or a restart shows up as a longer span on the next tick, not as a
permanent lag or a gap in the series.

A site, not a generator, is the unit of work: bulk storage is shared, so its
level can only be advanced with every generator drawing on it in view.

The work itself is `run_site_span` — the same function the backfill calls. Live
data and history are therefore indistinguishable downstream, which is the
property that makes a 30-day chart continue smoothly into the present.

Only one process may tick at a time. Readings would survive concurrent writers
(ON CONFLICT DO NOTHING) but events would not — they have no natural key — so a
second replica would silently duplicate every refill. A transaction-scoped
advisory lock makes the second writer skip its tick instead.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.services.backfill import load_site_specs, load_vehicle_specs
from app.services.persistence import (
    insert_events,
    insert_readings,
    insert_tank_readings,
    insert_vehicle_readings,
    load_generator_cursors,
    load_tank_states,
    load_vehicle_states,
    save_site_state,
    save_vehicle_state,
    touch_tank_last_seen,
)
from app.services.platform_settings import load_tuning
from app.simulation.engine import (
    EventSample,
    ReadingSample,
    SiteSpec,
    SiteState,
    TankReadingSample,
    initial_site_state,
)
from app.simulation.site import run_site_span
from app.simulation.vehicle import (
    VehicleReadingSample,
    VehicleSpec,
    VehicleState,
    initial_vehicle_state,
    run_vehicle_span,
)

logger = logging.getLogger(__name__)

# Arbitrary but fixed: every replica must derive the same lock id. 0x46554C50
# is "FULP" in ASCII, which makes it recognisable in pg_locks.
TICK_LOCK_KEY = 0x46554C50

# Ceiling on how far one tick will advance a single site. After long downtime
# the catch-up is spread over several ticks rather than blocking the event loop
# on one enormous synchronous span. At the default 5 minutes per step this is
# just under a week per tick.
MAX_CATCHUP_STEPS = 2_000

# The most recent completed tick in this process, for the admin System page.
# Per process: a replica that skipped on the lock keeps its own older report.
LAST_REPORT: "TickReport | None" = None

# Vehicles step a minute at a time, so their ceiling is in minutes: three days,
# a fraction of a second of arithmetic per machine.
VEHICLE_MAX_CATCHUP_MINUTES = 3 * 24 * 60


@dataclass(frozen=True)
class Advance:
    """One site's planned work for this tick."""

    spec: SiteSpec
    state: SiteState
    until: datetime
    # True when the span was capped by MAX_CATCHUP_STEPS and this site is
    # still behind wall-clock after the tick completes.
    clamped: bool = False


@dataclass
class TickReport:
    """What a tick did. Returned to the admin endpoint and logged."""

    started_at: datetime
    sites: int = 0
    generators: int = 0
    readings: int = 0
    tank_readings: int = 0
    events: int = 0
    vehicles: int = 0
    vehicle_readings: int = 0
    # Set when another process held the lock; nothing was written.
    skipped_locked: bool = False
    # Sites still behind wall-clock after this tick.
    still_catching_up: list[uuid.UUID] = field(default_factory=list)


def plan_advance(
    spec: SiteSpec,
    state: SiteState | None,
    now: datetime,
    minutes_per_tick: float,
    seed: int,
    max_steps: int = MAX_CATCHUP_STEPS,
) -> Advance | None:
    """Decide how far one site moves this tick. Pure.

    Returns None when there is nothing to do — the site's cursor has already
    reached `now`, which happens whenever the tick interval is shorter than the
    simulated step.

    A site with no persisted cursor is new: it was added after the initial
    backfill. It starts one step behind `now` so it begins emitting immediately
    rather than silently backfilling a month of history on a live tick.
    """
    if state is None:
        state = initial_site_state(spec, now - timedelta(minutes=minutes_per_tick), seed)

    if state.simulated_at >= now:
        return None

    horizon = state.simulated_at + timedelta(minutes=minutes_per_tick * max_steps)
    if horizon < now:
        return Advance(spec=spec, state=state, until=horizon, clamped=True)

    return Advance(spec=spec, state=state, until=now, clamped=False)


def plan_vehicle_advance(
    spec: VehicleSpec,
    state: VehicleState | None,
    now: datetime,
    seed: int,
    max_minutes: int = VEHICLE_MAX_CATCHUP_MINUTES,
) -> tuple[VehicleState, datetime, bool] | None:
    """Vehicle counterpart of `plan_advance`: (state, until, clamped) or None."""
    if state is None:
        state = initial_vehicle_state(spec, now - timedelta(minutes=1), seed)
    if state.simulated_at + timedelta(minutes=1) > now:
        return None
    horizon = state.simulated_at + timedelta(minutes=max_minutes)
    if horizon < now:
        return state, horizon, True
    return state, now, False


def assemble_site_state(
    spec: SiteSpec,
    cursors: dict[uuid.UUID, object],
    tank_states: dict[uuid.UUID, object],
) -> SiteState | None:
    """Rebuild a site's state from the two persisted halves.

    Returns None when the site has never been simulated, or when any of its
    tanks is missing a level — a half-persisted site is treated as new rather
    than resumed from an inconsistent mix of fresh and stale rows.
    """
    generator_ids = [generator.id for generator in spec.generators]
    present = [cursors[gid] for gid in generator_ids if gid in cursors]
    if not present:
        return None

    tank_ids = [generator.day_tank.id for generator in spec.generators]
    tank_ids += [tank.id for tank in spec.bulk_tanks]
    if any(tank_id not in tank_states for tank_id in tank_ids):
        return None

    # Generators at a site advance in lockstep, so any cursor carries the
    # site's position; take the oldest so a newly added unit cannot drag the
    # site forward past history its siblings have not generated yet.
    anchor = min(present, key=lambda row: row.simulated_at)  # type: ignore[attr-defined]

    return SiteState(
        simulated_at=anchor.simulated_at,  # type: ignore[attr-defined]
        tick_index=anchor.tick_index,  # type: ignore[attr-defined]
        tanks={tank_id: tank_states[tank_id] for tank_id in tank_ids},  # type: ignore[misc]
        engine_running={
            gid: bool(cursors[gid].engine_running)  # type: ignore[attr-defined]
            for gid in generator_ids
            if gid in cursors
        },
    )


async def _acquire_lock(session: AsyncSession) -> bool:
    """Take the tick lock for the current transaction, or report it taken.

    The transaction-scoped variant releases on commit or rollback, so a crashed
    ticker cannot wedge the lock the way the session-scoped one would when its
    connection is returned to the pool still holding it.
    """
    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": TICK_LOCK_KEY}
    )
    return bool(result.scalar())


async def run_tick(
    session: AsyncSession,
    settings: Settings,
    now: datetime | None = None,
) -> TickReport:
    """Advance the whole fleet to `now` and persist the result.

    Commits before returning: the caller's session is left clean either way.
    """
    now = now or datetime.now(UTC)
    report = TickReport(started_at=now)

    if not await _acquire_lock(session):
        logger.debug("tick skipped: another process holds the lock")
        report.skipped_locked = True
        await session.rollback()
        return report

    # Admin overrides merged over the environment, re-read every tick so a
    # change in the console applies without a restart.
    theft, vehicle_tuning = await load_tuning(session, settings)

    specs = await load_site_specs(session)
    cursors = await load_generator_cursors(session)
    tank_states = await load_tank_states(session)

    # Accumulated across the fleet rather than written per site: a tick
    # normally produces one row each, and a dozen single-row round-trips cost
    # far more than the arithmetic that produced them.
    all_readings: list[ReadingSample] = []
    all_tank_readings: list[TankReadingSample] = []
    all_events: list[EventSample] = []
    next_states: list[tuple[SiteSpec, SiteState]] = []

    for spec in specs:
        plan = plan_advance(
            spec,
            assemble_site_state(spec, cursors, tank_states),
            now,
            settings.sim_minutes_per_tick,
            settings.sim_seed,
        )
        if plan is None:
            continue

        state, readings, tank_readings, events = run_site_span(
            plan.spec,
            plan.state,
            plan.until,
            settings.sim_minutes_per_tick,
            settings.sim_seed,
            theft,
            settings.refill_window,
        )

        all_readings.extend(readings)
        all_tank_readings.extend(tank_readings)
        all_events.extend(events)
        next_states.append((spec, state))
        report.sites += 1
        report.generators += len(spec.generators)

        if plan.clamped:
            report.still_catching_up.append(spec.id)

    vehicle_readings: list[VehicleReadingSample] = []
    vehicle_states: list[tuple[VehicleSpec, VehicleState]] = []
    saved_vehicles = await load_vehicle_states(session)
    for vehicle in await load_vehicle_specs(session):
        vehicle_plan = plan_vehicle_advance(
            vehicle, saved_vehicles.get(vehicle.id), now, settings.sim_seed
        )
        if vehicle_plan is None:
            continue
        start_state, until, clamped = vehicle_plan
        state, samples, events = run_vehicle_span(
            vehicle, start_state, until, settings.sim_seed, vehicle_tuning
        )
        vehicle_readings.extend(samples)
        all_events.extend(events)
        vehicle_states.append((vehicle, state))
        report.vehicles += 1
        if clamped:
            report.still_catching_up.append(vehicle.id)

    if vehicle_readings:
        report.vehicle_readings = await insert_vehicle_readings(session, vehicle_readings)
    for vehicle, state in vehicle_states:
        await save_vehicle_state(session, vehicle.id, state)

    if all_readings:
        report.readings = await insert_readings(session, all_readings)
    if all_tank_readings:
        report.tank_readings = await insert_tank_readings(session, all_tank_readings)
        await touch_tank_last_seen(session, all_tank_readings)
    if all_events:
        report.events = await insert_events(session, all_events)
    for spec, state in next_states:
        await save_site_state(session, spec, state)

    await session.commit()

    global LAST_REPORT
    LAST_REPORT = report

    if report.still_catching_up:
        logger.warning(
            "%d site(s) capped at %d steps this tick and remain behind wall-clock",
            len(report.still_catching_up),
            MAX_CATCHUP_STEPS,
        )
    if report.readings or report.events or report.vehicle_readings:
        logger.info(
            "tick advanced %d site(s) / %d generator(s) / %d vehicle(s): "
            "%d readings, %d tank readings, %d vehicle readings, %d events",
            report.sites,
            report.generators,
            report.vehicles,
            report.readings,
            report.tank_readings,
            report.vehicle_readings,
            report.events,
        )

    return report
