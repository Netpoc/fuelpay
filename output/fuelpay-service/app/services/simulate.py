"""Operator-driven incidents.

Waiting for a siphon to occur naturally means waiting days — theft is a ~1.5%
chance per tank per day, at night, with the engine off. That is correct
behaviour and useless for showing someone what a drain looks like.

These helpers stage the *precondition* in the simulation state and then run the
ordinary stepper. The engine emits the SUSPECTED_DRAIN / DELIVERY / LOW_FUEL
events itself, from the same code path the live ticker and the backfill use.
Nothing here writes a synthetic event, so an injected incident is
indistinguishable downstream from one that happened on its own — which is the
whole point of being able to demonstrate it.

Requests address a *generator*, because that is what an operator picks in the
UI, but stepping happens at site level: bulk storage is shared, so a site
cannot be advanced one generator at a time. The whole site moves, and the
result reports the target generator's day tank.

Note what running steps here does to the clock: it advances that site's
`simulated_at` ahead of the others, and the live ticker will then idle it
(`plan_advance` returns None) until wall-clock catches up. That is the same
overshoot `run_site_span` already produces on a normal tick, and it self-heals.
"""

import logging
import math
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.entities import EventType
from app.services.backfill import load_site_specs
from app.services.persistence import (
    insert_events,
    insert_readings,
    insert_tank_readings,
    load_generator_cursors,
    load_tank_states,
    save_site_state,
    touch_tank_last_seen,
)
from app.services.ticker import assemble_site_state
from app.simulation.engine import (
    THEFT_RATE_FRACTION_PER_MIN,
    EventSample,
    GeneratorSpec,
    SiteSpec,
    SiteState,
    initial_site_state,
)
from app.simulation.site import step_site
from app.tuning import RefillWindow

logger = logging.getLogger(__name__)

# Ceiling on how far one request may fast-forward a site. Past this it stalls
# too far ahead of the fleet, since the live ticker idles a site whose
# simulated clock is beyond wall-clock.
MAX_STEPS = 24


def steps_to_drain(volume_l: float, capacity_l: float, minutes_per_step: float) -> int:
    """How many steps a siphon of `volume_l` needs at the pump's rate.

    Deriving this rather than fixing it matters: the pump moves a fraction of
    *capacity per simulated minute*, so a hard-coded step count silently
    under-drains whenever `sim_minutes_per_tick` is lowered — which is exactly
    what the livelier demo profile does.
    """
    per_step = capacity_l * THEFT_RATE_FRACTION_PER_MIN * minutes_per_step
    if per_step <= 0:
        return 1
    return max(1, min(MAX_STEPS, math.ceil(volume_l / per_step)))


class GeneratorNotFound(LookupError):
    """The generator does not exist, is not ACTIVE, or belongs to another tenant."""


@dataclass
class SimulateResult:
    generator_id: uuid.UUID
    steps: int
    readings: int
    events: list[EventSample]
    fuel_level_l: float
    fuel_level_pct: float
    simulated_from: datetime
    simulated_to: datetime
    # Set only when the request had to move a tank before the engine would
    # act — the level it was moved from, so the jump is attributable.
    staged_from_l: float | None = None

    @property
    def event_types(self) -> list[EventType]:
        return [event.event_type for event in self.events]


async def _load_target(
    session: AsyncSession,
    generator_id: uuid.UUID,
    organisation_id: uuid.UUID,
) -> tuple[SiteSpec, GeneratorSpec]:
    """Resolve a generator to its site spec, scoped to the calling tenant."""
    specs = await load_site_specs(session, organisation_id, generator_id)
    for site in specs:
        for generator in site.generators:
            if generator.id == generator_id:
                return site, generator
    raise GeneratorNotFound(str(generator_id))


async def _load_state(
    session: AsyncSession,
    spec: SiteSpec,
    now: datetime,
    seed: int,
) -> SiteState:
    """Current cursor for one site, or a fresh one if it has never ticked."""
    cursors = await load_generator_cursors(session)
    tank_states = await load_tank_states(session)
    state = assemble_site_state(spec, cursors, tank_states)
    if state is None:
        return initial_site_state(spec, now, seed)
    return state


def _with_tank(state: SiteState, tank_id: uuid.UUID, **changes) -> SiteState:
    """Return `state` with one tank's fields replaced."""
    tanks = dict(state.tanks)
    tanks[tank_id] = replace(tanks[tank_id], **changes)
    return SiteState(
        simulated_at=state.simulated_at,
        tick_index=state.tick_index,
        tanks=tanks,
        engine_running=dict(state.engine_running),
    )


async def _run(
    session: AsyncSession,
    settings: Settings,
    spec: SiteSpec,
    generator: GeneratorSpec,
    state: SiteState,
    steps: int,
    refill_window: RefillWindow | None = None,
) -> SimulateResult:
    """Step one site `steps` times and persist everything it produced."""
    started_at = state.simulated_at
    readings = []
    tank_readings = []
    events: list[EventSample] = []

    for _ in range(steps):
        result = step_site(
            spec,
            state,
            settings.sim_minutes_per_tick,
            settings.sim_seed,
            settings.theft_tuning,
            refill_window or settings.refill_window,
        )
        state = result.state
        readings.extend(result.readings)
        tank_readings.extend(result.tank_readings)
        events.extend(result.events)

    written = await insert_readings(session, readings)
    await insert_tank_readings(session, tank_readings)
    await touch_tank_last_seen(session, tank_readings)
    await insert_events(session, events)
    await save_site_state(session, spec, state)
    await session.commit()

    capacity = generator.day_tank.capacity_l
    level = state.tanks[generator.day_tank.id].level_l
    return SimulateResult(
        generator_id=generator.id,
        steps=steps,
        readings=written,
        events=events,
        fuel_level_l=round(level, 2),
        fuel_level_pct=round((level / capacity) * 100.0, 2) if capacity else 0.0,
        simulated_from=started_at,
        simulated_to=state.simulated_at,
    )


async def inject_drain(
    session: AsyncSession,
    settings: Settings,
    generator_id: uuid.UUID,
    organisation_id: uuid.UUID,
    volume_l: float | None = None,
    steps: int | None = None,
    now: datetime | None = None,
    target_bulk: bool = False,
) -> SimulateResult:
    """Start a siphon on one generator's day tank, or on the site's bulk store.

    Sets `pending_drain_l`, which the engine already drains down over several
    ticks at the pump's rate — so this produces the multi-event series a real
    theft produces, not one instantaneous drop.

    `target_bulk` aims at the largest bulk tank instead. That is the theft that
    actually costs a Nigerian bank site money, so it is worth being able to
    demonstrate directly.

    `volume_l` defaults to the midpoint of the configured theft range, clamped
    to what is actually in the tank. `steps` defaults to however many the pump
    needs to move that volume, so the siphon actually completes rather than
    stopping partway.
    """
    spec, generator = await _load_target(session, generator_id, organisation_id)
    state = await _load_state(session, spec, now or datetime.now(UTC), settings.sim_seed)

    tank = generator.day_tank
    if target_bulk:
        if not spec.bulk_tanks:
            raise GeneratorNotFound(f"site for {generator_id} has no instrumented bulk tank")
        tank = max(spec.bulk_tanks, key=lambda t: state.tanks[t.id].level_l)

    if volume_l is None:
        theft = settings.theft_tuning
        midpoint = (theft.volume_min_fraction + theft.volume_max_fraction) / 2.0
        volume_l = tank.capacity_l * midpoint

    requested = volume_l
    available = state.tanks[tank.id].level_l
    volume_l = max(0.0, min(volume_l, available))
    if volume_l < requested:
        logger.info(
            "drain on tank %s clamped from %.1f L to %.1f L — that is all it holds",
            tank.id,
            requested,
            volume_l,
        )

    if steps is None:
        steps = steps_to_drain(volume_l, tank.capacity_l, settings.sim_minutes_per_tick)

    staged = _with_tank(state, tank.id, pending_drain_l=volume_l)
    return await _run(session, settings, spec, generator, staged, steps)


async def set_level(
    session: AsyncSession,
    settings: Settings,
    generator_id: uuid.UUID,
    organisation_id: uuid.UUID,
    level_l: float | None = None,
    level_pct: float | None = None,
    steps: int = 1,
    now: datetime | None = None,
    refill_window: RefillWindow | None = None,
) -> SimulateResult:
    """Move the generator's day tank to a given level, then step.

    The primitive behind staging any level-driven incident: park the tank just
    above its reorder threshold and the next steps emit LOW_FUEL as consumption
    carries it across.
    """
    spec, generator = await _load_target(session, generator_id, organisation_id)
    state = await _load_state(session, spec, now or datetime.now(UTC), settings.sim_seed)

    capacity = generator.day_tank.capacity_l
    if level_l is None:
        if level_pct is None:
            raise ValueError("Provide either level_l or level_pct.")
        level_l = capacity * (level_pct / 100.0)

    level_l = max(0.0, min(level_l, capacity))

    staged = _with_tank(
        state,
        generator.day_tank.id,
        level_l=level_l,
        # Abandon any siphon in progress — the caller is setting the level
        # explicitly and a leftover drain would immediately contradict it.
        pending_drain_l=0.0,
    )
    return await _run(session, settings, spec, generator, staged, steps, refill_window)


async def force_refill(
    session: AsyncSession,
    settings: Settings,
    generator_id: uuid.UUID,
    organisation_id: uuid.UUID,
    steps: int = 1,
    now: datetime | None = None,
) -> SimulateResult:
    """Dispatch a tanker to the site's bulk storage now.

    Under the two-tier model this is a delivery into bulk, not a top-up of the
    generator's day tank — that is what a tanker visit actually is. The day
    tank is replenished by transfer, which needs no dispatching: it happens
    whenever the tank drops below its threshold and there is bulk fuel behind
    it.

    Works by opening the delivery window rather than by draining a tank. An
    earlier version dropped the level below the emergency threshold to force
    the engine's hand, which wrote a cliff into the telemetry with no drain
    event behind it — in a product whose whole job is spotting fuel
    disappearing without explanation, that is the one artefact we must not
    manufacture.

    A bulk tank already under its reorder threshold is filled exactly as it
    would have been in the morning: no level change at all, `emergency`
    correctly false. A fuller tank has no business receiving a delivery, so it
    is first lowered to just under the threshold — a staged precondition,
    reported back as `staged_from_l` so the caller can see the discontinuity is
    theirs.
    """
    spec, generator = await _load_target(session, generator_id, organisation_id)
    state = await _load_state(session, spec, now or datetime.now(UTC), settings.sim_seed)

    if not spec.bulk_tanks:
        raise GeneratorNotFound(f"site for {generator_id} has no instrumented bulk tank")

    # Tankers deliver at any hour for this request; the point is to see a
    # delivery now, not to wait until 08:00 simulated time.
    all_hours = RefillWindow(start_hour=0, end_hour=24)

    # The emptiest tank is the one a driver would fill.
    target = min(spec.bulk_tanks, key=lambda t: state.tanks[t.id].level_l)
    threshold_l = target.capacity_l * (target.reorder_threshold_pct / 100.0)
    current = state.tanks[target.id].level_l

    if current < threshold_l:
        return await _run(session, settings, spec, generator, state, steps, all_hours)

    logger.info(
        "refill on site %s staged bulk tank %s down from %.1f L to just under its %.1f L "
        "threshold — it was too full to warrant a delivery",
        spec.id,
        target.id,
        current,
        threshold_l,
    )
    staged = _with_tank(state, target.id, level_l=threshold_l * 0.98)
    result = await _run(session, settings, spec, generator, staged, steps, all_hours)
    result.staged_from_l = round(current, 2)
    return result
