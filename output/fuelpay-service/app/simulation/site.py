"""Site-level simulation: the three-hop fuel path.

    tanker  ->  BULK (5000 L+)  ->  DAY (in-built)  ->  engine
             delivery          transfer           consumption

A site is the unit of simulation rather than a generator, because bulk storage
is shared: its level is not a property of any one generator drawing from it.

Order within a tick is deliberate:

1. burn      — engines draw from their day tanks
2. theft     — siphoning, weighted towards bulk storage where the fuel is
3. transfer  — day tanks below threshold pull from bulk
4. delivery  — bulk tanks below threshold call a tanker
5. sensors   — signal state resolves, then surviving tanks emit readings

Replenishment follows depletion so a tank that dips below threshold mid-tick is
topped up in the same tick rather than emitting a spurious low-fuel reading
first. Theft precedes transfer for the same reason it happens in real life:
the thief is not waiting for the pump.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.models.entities import EventType, TankKind
from app.simulation.engine import (
    EMERGENCY_REFILL_PCT,
    REFILL_TARGET_MAX_PCT,
    REFILL_TARGET_MIN_PCT,
    THEFT_RATE_FRACTION_PER_MIN,
    EventSample,
    ReadingSample,
    SiteSpec,
    SiteState,
    TankReadingSample,
    TankSpec,
    TankState,
    burn,
    generator_reading,
    in_hour_window,
    measure,
    rng_for,
)
from app.tuning import (
    DEFAULT_DELIVERY,
    DEFAULT_REFILL_WINDOW,
    DEFAULT_SENSOR,
    DEFAULT_THEFT,
    DEFAULT_TRANSFER,
    DeliveryTuning,
    RefillWindow,
    SensorTuning,
    TheftTuning,
    TransferTuning,
)

# Day tanks sit inside the genset housing, usually behind a fence and often
# within sight of a guard. Bulk storage is the softer target, so a day tank is
# siphoned at a fraction of the rate.
DAY_TANK_THEFT_SCALE = 0.4

# A running engine deters theft from the tank feeding it: the set is noisy,
# hot, and someone is usually attending it. It is NOT a deterrent for bulk
# storage, which sits apart in its own compound. Gating bulk theft on the
# engine would immunise every 24/7 site — telecom towers and bank branches
# both run continuously through an outage — which is precisely the population
# the product exists to protect.
ENGINE_DETERS_THEFT_FROM = (TankKind.DAY,)


@dataclass(frozen=True)
class SiteTickResult:
    state: SiteState
    readings: list[ReadingSample]
    tank_readings: list[TankReadingSample]
    events: list[EventSample]


def _threshold_l(spec: TankSpec) -> float:
    return spec.capacity_l * (spec.reorder_threshold_pct / 100.0)


def _siphon(
    spec: TankSpec,
    state: TankState,
    moment: datetime,
    minutes: float,
    seed: int,
    tick_index: int,
    theft: TheftTuning,
    engine_running: bool,
) -> tuple[TankState, float, list[EventSample]]:
    """Start and/or advance a siphon on one tank.

    A siphon spans several ticks: a pump moves a bounded number of litres per
    minute, so a large theft shows up in the data as a steep but finite slope
    rather than a single impossible step.
    """
    pending = state.pending_drain_l
    level = state.level_l
    events: list[EventSample] = []

    if pending <= 0.0 and in_hour_window(moment, theft.window_start_hour, theft.window_end_hour):
        rng = rng_for(seed, spec.id, tick_index, "theft")
        scale = DAY_TANK_THEFT_SCALE if spec.kind is TankKind.DAY else 1.0
        tick_probability = theft.probability_per_day * scale * (minutes / 1440.0)
        deterred = engine_running and spec.kind in ENGINE_DETERS_THEFT_FROM
        if not deterred and rng.random() < tick_probability:
            fraction = rng.uniform(theft.volume_min_fraction, theft.volume_max_fraction)
            pending = min(spec.capacity_l * fraction, level)

    drained = 0.0
    if pending > 0.0:
        siphon_capacity = spec.capacity_l * THEFT_RATE_FRACTION_PER_MIN * minutes
        drained = min(pending, siphon_capacity, level)
        level -= drained
        pending -= drained

        if drained > 0.0:
            events.append(
                EventSample(
                    organisation_id=spec.organisation_id,
                    tank_id=spec.id,
                    generator_id=None,
                    event_type=EventType.SUSPECTED_DRAIN,
                    occurred_at=moment,
                    volume_l=-drained,
                    fuel_level_l=level,
                    detail={
                        # Marks this as simulator ground truth. A detector that
                        # infers drains from readings alone can be scored
                        # against it.
                        "ground_truth": True,
                        "tank_kind": spec.kind.value,
                        "remaining_to_siphon_l": round(pending, 2),
                    },
                )
            )

    return replace(state, level_l=level, pending_drain_l=pending), drained, events


def _deliver(
    spec: TankSpec,
    state: TankState,
    moment: datetime,
    seed: int,
    tick_index: int,
    delivery: DeliveryTuning,
    window: RefillWindow,
) -> tuple[TankState, list[EventSample]]:
    """Call a tanker for a bulk tank that has fallen below its threshold.

    The billed volume and the delivered volume are not always the same number.
    That gap is the fraud a bulk-tank sensor exists to expose: without one, the
    site has no way to contest the invoice.
    """
    level = state.level_l
    events: list[EventSample] = []

    if level >= _threshold_l(spec):
        return state, events

    in_window = in_hour_window(moment, window.start_hour, window.end_hour)
    critical = level < spec.capacity_l * EMERGENCY_REFILL_PCT
    if not (in_window or critical):
        return state, events

    rng = rng_for(seed, spec.id, tick_index, "delivery")
    target = spec.capacity_l * rng.uniform(REFILL_TARGET_MIN_PCT, REFILL_TARGET_MAX_PCT)
    billed = max(0.0, target - level)
    if billed <= 0.0:
        return state, events

    delivered = billed
    if rng.random() < delivery.short_probability:
        shortfall_fraction = rng.uniform(delivery.short_min_fraction, delivery.short_max_fraction)
        delivered = billed * (1.0 - shortfall_fraction)

    # Physically cannot take more than the tank holds.
    delivered = min(delivered, spec.capacity_l - level)
    level += delivered
    shortfall = billed - delivered

    events.append(
        EventSample(
            organisation_id=spec.organisation_id,
            tank_id=spec.id,
            generator_id=None,
            event_type=EventType.DELIVERY,
            occurred_at=moment,
            volume_l=delivered,
            fuel_level_l=level,
            detail={
                "billed_l": round(billed, 2),
                "delivered_l": round(delivered, 2),
                "emergency": critical and not in_window,
            },
        )
    )

    if shortfall > billed * delivery.tolerance_fraction:
        events.append(
            EventSample(
                organisation_id=spec.organisation_id,
                tank_id=spec.id,
                generator_id=None,
                event_type=EventType.SHORT_DELIVERY,
                occurred_at=moment,
                volume_l=-shortfall,
                fuel_level_l=level,
                detail={
                    "ground_truth": True,
                    "billed_l": round(billed, 2),
                    "delivered_l": round(delivered, 2),
                    "shortfall_pct": round(shortfall / billed * 100.0, 2),
                },
            )
        )

    return replace(state, level_l=level), events


def _resolve_sensor(
    spec: TankSpec,
    state: TankState,
    moment: datetime,
    minutes: float,
    seed: int,
    tick_index: int,
    sensor: SensorTuning,
    outflow_l: float,
) -> tuple[TankState, bool, list[EventSample]]:
    """Advance the tank's connectivity, returning whether it reports this tick.

    Returning False is the whole point: a tank with no signal emits no reading
    at all. Absence of rows is how a gap is represented, because inventing a
    value for an unobserved period is precisely the error that would let fuel
    disappear unnoticed.
    """
    events: list[EventSample] = []

    if state.signal_out_ticks > 0:
        remaining = state.signal_out_ticks - 1
        if remaining > 0:
            return replace(state, signal_out_ticks=remaining), False, events

        # Signal restored: reconcile what happened while we were blind.
        events.append(
            EventSample(
                organisation_id=spec.organisation_id,
                tank_id=spec.id,
                generator_id=None,
                event_type=EventType.SIGNAL_RESTORED,
                occurred_at=moment,
                volume_l=None,
                fuel_level_l=state.level_l,
                detail={"tank_kind": spec.kind.value},
            )
        )

        level_at_loss = state.level_at_signal_loss_l
        if level_at_loss is not None:
            # This tick's own draw counts as accounted too: the reconnect
            # happens after the burn, so the level being compared already
            # reflects it.
            accounted = state.accounted_outflow_l + outflow_l
            unexplained = (level_at_loss - state.level_l) - accounted
            if unexplained > spec.capacity_l * sensor.unverified_loss_threshold_fraction:
                events.append(
                    EventSample(
                        organisation_id=spec.organisation_id,
                        tank_id=spec.id,
                        generator_id=None,
                        event_type=EventType.UNVERIFIED_LOSS,
                        occurred_at=moment,
                        volume_l=-unexplained,
                        fuel_level_l=state.level_l,
                        detail={
                            # Deliberately not SUSPECTED_DRAIN. Nobody was
                            # watching, so this cannot be attributed to theft
                            # or to consumption — only flagged as unexplained.
                            "level_at_signal_loss_l": round(level_at_loss, 2),
                            "accounted_outflow_l": round(accounted, 2),
                            "unexplained_l": round(unexplained, 2),
                        },
                    )
                )

        return (
            replace(
                state,
                signal_out_ticks=0,
                level_at_signal_loss_l=None,
                accounted_outflow_l=0.0,
            ),
            True,
            events,
        )

    rng = rng_for(seed, spec.id, tick_index, "sensor_health")
    if rng.random() < sensor.dropout_probability_per_day * (minutes / 1440.0):
        out_ticks = rng.randint(sensor.min_out_ticks, sensor.max_out_ticks)
        events.append(
            EventSample(
                organisation_id=spec.organisation_id,
                tank_id=spec.id,
                generator_id=None,
                event_type=EventType.SIGNAL_LOSS,
                occurred_at=moment,
                volume_l=None,
                fuel_level_l=state.level_l,
                detail={"tank_kind": spec.kind.value, "expected_out_ticks": out_ticks},
            )
        )
        return (
            replace(
                state,
                signal_out_ticks=out_ticks,
                level_at_signal_loss_l=state.level_l,
                accounted_outflow_l=0.0,
            ),
            False,
            events,
        )

    return state, True, events


def step_site(
    spec: SiteSpec,
    state: SiteState,
    minutes: float,
    seed: int,
    theft: TheftTuning = DEFAULT_THEFT,
    refill_window: RefillWindow = DEFAULT_REFILL_WINDOW,
    delivery: DeliveryTuning = DEFAULT_DELIVERY,
    transfer: TransferTuning = DEFAULT_TRANSFER,
    sensor: SensorTuning = DEFAULT_SENSOR,
) -> SiteTickResult:
    """Advance one site by `minutes` and emit everything it produced."""
    moment = state.simulated_at + timedelta(minutes=minutes)
    tick = state.tick_index

    tanks = dict(state.tanks)
    engines = dict(state.engine_running)
    events: list[EventSample] = []
    readings: list[ReadingSample] = []
    tank_readings: list[TankReadingSample] = []

    # Litres out of each tank this tick, split by cause, for the reading rows
    # and for signal-gap accounting.
    consumed_by_tank: dict[uuid.UUID, float] = {}
    transferred_by_tank: dict[uuid.UUID, float] = {}

    day_specs = {generator.day_tank.id: generator.day_tank for generator in spec.generators}
    all_specs: dict[uuid.UUID, TankSpec] = {**day_specs}
    for bulk in spec.bulk_tanks:
        all_specs[bulk.id] = bulk

    # --- 1. burn -------------------------------------------------------
    burns = {}
    for generator in spec.generators:
        tank_id = generator.day_tank.id
        tank_state = tanks[tank_id]
        result = burn(
            spec=generator,
            moment=moment,
            day_tank_level_l=tank_state.level_l,
            was_running=engines.get(generator.id, False),
            minutes=minutes,
            seed=seed,
            tick_index=tick,
        )
        burns[generator.id] = result
        events.extend(result.events)
        engines[generator.id] = result.running

        tanks[tank_id] = replace(tank_state, level_l=tank_state.level_l - result.consumed_l)
        consumed_by_tank[tank_id] = result.consumed_l

    # --- 2. theft ------------------------------------------------------
    site_has_running_engine = any(burns[g.id].running for g in spec.generators)
    for tank_id, tank_spec in all_specs.items():
        # A day tank's own engine is the deterrent; for bulk storage, any
        # engine running at the site means someone is likely about.
        engine_running = (
            burns[_generator_for_day_tank(spec, tank_id)].running
            if tank_spec.kind is TankKind.DAY
            else site_has_running_engine
        )
        tanks[tank_id], _, theft_events = _siphon(
            spec=tank_spec,
            state=tanks[tank_id],
            moment=moment,
            minutes=minutes,
            seed=seed,
            tick_index=tick,
            theft=theft,
            engine_running=engine_running,
        )
        events.extend(theft_events)

    # --- 3. transfer: bulk -> day --------------------------------------
    for generator in spec.generators:
        day_spec = generator.day_tank
        day_state = tanks[day_spec.id]
        if day_state.level_l >= _threshold_l(day_spec):
            continue

        rng = rng_for(seed, day_spec.id, tick, "transfer")
        target = day_spec.capacity_l * rng.uniform(
            transfer.target_min_fraction, transfer.target_max_fraction
        )
        wanted = max(0.0, target - day_state.level_l)
        # A pump moves a bounded volume per minute, so a big day tank fills
        # over several ticks instead of jumping to full.
        wanted = min(wanted, transfer.pump_rate_lpm * minutes)

        moved_total = 0.0
        for bulk in spec.bulk_tanks:
            if wanted <= 0.0:
                break
            bulk_state = tanks[bulk.id]
            moved = min(wanted, bulk_state.level_l)
            if moved <= 0.0:
                continue

            tanks[bulk.id] = replace(bulk_state, level_l=bulk_state.level_l - moved)
            transferred_by_tank[bulk.id] = transferred_by_tank.get(bulk.id, 0.0) + moved
            moved_total += moved
            wanted -= moved

            events.append(
                EventSample(
                    organisation_id=spec.organisation_id,
                    tank_id=bulk.id,
                    generator_id=generator.id,
                    event_type=EventType.TRANSFER,
                    occurred_at=moment,
                    volume_l=moved,
                    fuel_level_l=tanks[bulk.id].level_l,
                    detail={
                        "to_tank_id": str(day_spec.id),
                        "day_tank_level_l": round(day_state.level_l + moved_total, 2),
                    },
                )
            )

        if moved_total > 0.0:
            tanks[day_spec.id] = replace(
                tanks[day_spec.id], level_l=tanks[day_spec.id].level_l + moved_total
            )
        else:
            # Nothing left upstream. The day tank is running down with no
            # bulk fuel behind it, which is the state worth alarming on.
            events.append(
                EventSample(
                    organisation_id=spec.organisation_id,
                    tank_id=day_spec.id,
                    generator_id=generator.id,
                    event_type=EventType.LOW_FUEL,
                    occurred_at=moment,
                    volume_l=None,
                    fuel_level_l=tanks[day_spec.id].level_l,
                    detail={
                        "threshold_l": round(_threshold_l(day_spec), 2),
                        "bulk_exhausted": True,
                    },
                )
            )

    # --- 4. delivery: tanker -> bulk -----------------------------------
    for bulk in spec.bulk_tanks:
        tanks[bulk.id], delivery_events = _deliver(
            spec=bulk,
            state=tanks[bulk.id],
            moment=moment,
            seed=seed,
            tick_index=tick,
            delivery=delivery,
            window=refill_window,
        )
        events.extend(delivery_events)

    # --- 5. sensors and emission ---------------------------------------
    for tank_id, tank_spec in all_specs.items():
        outflow = consumed_by_tank.get(tank_id, 0.0) + transferred_by_tank.get(tank_id, 0.0)
        tank_state, reports, sensor_events = _resolve_sensor(
            spec=tank_spec,
            state=tanks[tank_id],
            moment=moment,
            minutes=minutes,
            seed=seed,
            tick_index=tick,
            sensor=sensor,
            outflow_l=outflow,
        )
        events.extend(sensor_events)

        if not reports:
            # Blind this tick: accumulate what legitimately left the tank so
            # the reconnect can subtract it before alleging a loss.
            tanks[tank_id] = replace(
                tank_state, accounted_outflow_l=tank_state.accounted_outflow_l + outflow
            )
            continue

        tanks[tank_id] = tank_state
        agitated = tank_spec.kind is TankKind.DAY and _day_tank_engine_running(spec, tank_id, burns)
        rng = rng_for(seed, tank_id, tick, "sensor")
        reported = measure(tank_state.level_l, tank_spec.capacity_l, agitated, rng)

        tank_readings.append(
            TankReadingSample(
                tank_id=tank_id,
                organisation_id=tank_spec.organisation_id,
                time=moment,
                level_l=round(reported, 2),
                level_pct=round((reported / tank_spec.capacity_l) * 100.0, 2)
                if tank_spec.capacity_l
                else 0.0,
                consumed_l=round(consumed_by_tank.get(tank_id, 0.0), 4),
                transferred_l=round(transferred_by_tank.get(tank_id, 0.0), 4),
            )
        )

    # Generator telemetry always emits: the engine is instrumented separately
    # from the tank, so losing a fuel sensor blinds the level, not the load.
    for generator in spec.generators:
        day_state = tanks[generator.day_tank.id]
        rng = rng_for(seed, generator.id, tick, "gen_sensor")
        reported = measure(
            day_state.level_l,
            generator.day_tank.capacity_l,
            burns[generator.id].running,
            rng,
        )
        readings.append(
            generator_reading(generator, moment, burns[generator.id], reported, rng)
        )

    return SiteTickResult(
        state=SiteState(
            simulated_at=moment,
            tick_index=tick + 1,
            tanks=tanks,
            engine_running=engines,
        ),
        readings=readings,
        tank_readings=tank_readings,
        events=events,
    )


def _generator_for_day_tank(spec: SiteSpec, tank_id: uuid.UUID) -> uuid.UUID:
    for generator in spec.generators:
        if generator.day_tank.id == tank_id:
            return generator.id
    raise KeyError(f"no generator owns day tank {tank_id}")


def _day_tank_engine_running(spec: SiteSpec, tank_id: uuid.UUID, burns: dict) -> bool:
    return burns[_generator_for_day_tank(spec, tank_id)].running


def run_site_span(
    spec: SiteSpec,
    state: SiteState,
    until: datetime,
    minutes_per_step: float,
    seed: int,
    theft: TheftTuning = DEFAULT_THEFT,
    refill_window: RefillWindow = DEFAULT_REFILL_WINDOW,
    delivery: DeliveryTuning = DEFAULT_DELIVERY,
    transfer: TransferTuning = DEFAULT_TRANSFER,
    sensor: SensorTuning = DEFAULT_SENSOR,
) -> tuple[SiteState, list[ReadingSample], list[TankReadingSample], list[EventSample]]:
    """Repeatedly step until `until`, collecting all output.

    Used by the backfill path; the live ticker calls `step_site` once per tick.
    """
    readings: list[ReadingSample] = []
    tank_readings: list[TankReadingSample] = []
    events: list[EventSample] = []

    while state.simulated_at < until:
        result = step_site(
            spec, state, minutes_per_step, seed, theft, refill_window, delivery, transfer, sensor
        )
        state = result.state
        readings.extend(result.readings)
        tank_readings.extend(result.tank_readings)
        events.extend(result.events)

    return state, readings, tank_readings, events
