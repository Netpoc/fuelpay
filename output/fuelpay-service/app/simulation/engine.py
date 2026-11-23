"""The simulation stepper: specs, state and one generator's burn.

Pure and deterministic. Nothing here touches a database, a clock or global
randomness — the same inputs always produce the same outputs, which is what
lets backfill and live ticking share one code path and makes the whole thing
testable.

Randomness is derived from (seed, entity_id, tick_index, stream) via SHA-256,
not from a shared RNG. That keeps each generator's and each tank's stream
independent of iteration order and reproducible across processes.

Fuel is two-tier, so the unit of simulation is a *site*, not a generator: one
bulk tank feeds several day tanks, and its level cannot belong to any one of
them. This module supplies the pieces; `app.simulation.site` orchestrates them.

A note on truth vs. measurement: `TankState.level_l` is the physical truth. An
emitted reading carries sensor noise on top of it. They are deliberately not
the same number — a consumer that wants clean data should not get it, because
real fuel probes don't provide it.
"""

import hashlib
import math
import random
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.models.entities import EventType, SiteProfile, TankKind
from app.simulation.consumption import fuel_consumed_l, load_kw
from app.simulation.profiles import is_engine_running, target_load_fraction

# --- realism constants (reference doc section 7) ---

# Fuel probes quote 98-99% accuracy; +/-1% of capacity is the pessimistic end.
SENSOR_NOISE_PCT_OF_CAPACITY = 0.01
# Engine vibration disturbs the fuel surface. Only applies while running.
SLOSH_NOISE_PCT_OF_CAPACITY = 0.005
# Probes report discrete steps, not infinite precision.
LEVEL_QUANTISATION_L = 0.1
# Gensets are static installations; only the GPS fix wanders.
GPS_JITTER_METRES = 5.0

# Load varies around the profile baseline by this relative fraction.
LOAD_JITTER_RELATIVE = 0.06

# --- refill behaviour (reference doc section 6) ---

# Drivers rarely fill to the brim.
REFILL_TARGET_MIN_PCT = 0.90
REFILL_TARGET_MAX_PCT = 1.00
# Below this, replenish regardless of the hour — the site is about to go dark.
EMERGENCY_REFILL_PCT = 0.05

# --- theft behaviour ---

# Siphon pump rate, as a fraction of tank capacity per minute. A 1000 L tank
# drains at ~20 L/min, so a 300 L theft takes ~15 minutes. Not tunable: this is
# how fast a pump moves fuel, not a policy knob.
THEFT_RATE_FRACTION_PER_MIN = 0.02

METRES_PER_DEGREE_LAT = 111_320.0


@dataclass(frozen=True)
class TankSpec:
    """Immutable configuration of one instrumented tank.

    There is no "has a sensor" flag. Every tank FuelPay knows about has one by
    definition — an uninstrumented tank is invisible to the platform — so the
    sensor identity is simply part of the tank.
    """

    id: uuid.UUID
    organisation_id: uuid.UUID
    kind: TankKind
    capacity_l: float
    reorder_threshold_pct: float


@dataclass(frozen=True)
class GeneratorSpec:
    """Immutable configuration of one simulated unit and its day tank."""

    id: uuid.UUID
    organisation_id: uuid.UUID
    kva_rating: float
    power_factor: float
    profile: SiteProfile
    latitude: float
    longitude: float
    day_tank: TankSpec


@dataclass(frozen=True)
class SiteSpec:
    """A site: its bulk storage and the generators drawing from it."""

    id: uuid.UUID
    organisation_id: uuid.UUID
    profile: SiteProfile
    bulk_tanks: tuple[TankSpec, ...]
    generators: tuple[GeneratorSpec, ...]


@dataclass(frozen=True)
class TankState:
    """Mutable physical state of one tank, carried between ticks."""

    level_l: float
    pending_drain_l: float = 0.0
    # While positive the sensor is dark and the tank emits no readings.
    signal_out_ticks: int = 0
    level_at_signal_loss_l: float | None = None
    # Litres legitimately drawn since the signal dropped — burn for a day tank,
    # transfers out for a bulk tank. Without this, every outage that spans an
    # ordinary night's consumption would be reported as a suspected loss.
    accounted_outflow_l: float = 0.0


@dataclass(frozen=True)
class SiteState:
    """Everything a site needs to resume: where it is in time, and per-tank fuel."""

    simulated_at: datetime
    tick_index: int = 0
    # Keyed by tank id, covering both tiers.
    tanks: dict[uuid.UUID, TankState] = None  # type: ignore[assignment]
    # Keyed by generator id.
    engine_running: dict[uuid.UUID, bool] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # Frozen dataclass, so defaults have to be installed the hard way.
        # Mutable defaults cannot be shared across instances via `field`.
        if self.tanks is None:
            object.__setattr__(self, "tanks", {})
        if self.engine_running is None:
            object.__setattr__(self, "engine_running", {})


@dataclass(frozen=True)
class ReadingSample:
    """Generator telemetry. `fuel_level_l` is the day tank, kept on this row so
    existing single-tank queries and charts keep working unchanged."""

    generator_id: uuid.UUID
    organisation_id: uuid.UUID
    time: datetime
    fuel_level_l: float
    fuel_level_pct: float
    load_kw: float
    load_pct: float
    engine_running: bool
    consumed_l: float
    runtime_minutes: float
    latitude: float
    longitude: float


@dataclass(frozen=True)
class TankReadingSample:
    """One measured fuel level. Only emitted when the sensor has signal."""

    tank_id: uuid.UUID
    organisation_id: uuid.UUID
    time: datetime
    level_l: float
    level_pct: float
    consumed_l: float
    transferred_l: float


@dataclass(frozen=True)
class EventSample:
    organisation_id: uuid.UUID
    event_type: EventType
    occurred_at: datetime
    volume_l: float | None
    fuel_level_l: float | None
    detail: dict
    # Both optional: engine events have no tank, and a delivery into shared
    # bulk storage has no single generator.
    generator_id: uuid.UUID | None = None
    tank_id: uuid.UUID | None = None
    # Mobile machinery only, and then the two above stay None.
    vehicle_id: uuid.UUID | None = None


@dataclass(frozen=True)
class BurnResult:
    """What one generator did during a tick, before any replenishment."""

    generator_id: uuid.UUID
    running: bool
    load_fraction: float
    consumed_l: float
    runtime_minutes: float
    events: list[EventSample]


def rng_for(seed: int, entity_id: uuid.UUID, tick_index: int, stream: str) -> random.Random:
    """Deterministic per-(entity, tick, stream) RNG.

    SHA-256 rather than hash(): the built-in is salted per process, which would
    make runs irreproducible across restarts.
    """
    key = f"{seed}:{entity_id}:{tick_index}:{stream}".encode()
    digest = hashlib.sha256(key).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def in_hour_window(moment: datetime, start_hour: int, end_hour: int) -> bool:
    """Hour-window test that handles windows wrapping past midnight."""
    hour = moment.hour
    if start_hour <= end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def jitter_position(
    latitude: float, longitude: float, rng: random.Random
) -> tuple[float, float]:
    """Scatter the GPS fix within a few metres of the true installation point.

    Offsets are computed in metres then converted to degrees. Applying a fixed
    degree offset instead would make the real-world error vary with latitude.
    """
    north_m = rng.gauss(0.0, GPS_JITTER_METRES / 2.0)
    east_m = rng.gauss(0.0, GPS_JITTER_METRES / 2.0)

    lat_offset = north_m / METRES_PER_DEGREE_LAT
    # Guard the pole singularity where cos(lat) collapses to zero.
    cos_lat = max(math.cos(math.radians(latitude)), 1e-6)
    lon_offset = east_m / (METRES_PER_DEGREE_LAT * cos_lat)

    return latitude + lat_offset, longitude + lon_offset


def measure(
    true_level_l: float, capacity_l: float, agitated: bool, rng: random.Random
) -> float:
    """Apply sensor error to the true level to produce a reported level.

    `agitated` covers the extra slosh a running engine induces in its own day
    tank. A bulk tank sitting in the ground is never agitated.
    """
    noise = rng.gauss(0.0, SENSOR_NOISE_PCT_OF_CAPACITY * capacity_l)
    if agitated:
        noise += rng.gauss(0.0, SLOSH_NOISE_PCT_OF_CAPACITY * capacity_l)

    reported = true_level_l + noise
    reported = max(0.0, min(capacity_l, reported))
    return round(reported / LEVEL_QUANTISATION_L) * LEVEL_QUANTISATION_L


def burn(
    spec: GeneratorSpec,
    moment: datetime,
    day_tank_level_l: float,
    was_running: bool,
    minutes: float,
    seed: int,
    tick_index: int,
) -> BurnResult:
    """Advance one generator by `minutes`, drawing from its day tank.

    Replenishment is not handled here: a day tank is refilled by transfer from
    bulk storage, which is a site-level decision because the bulk tank is
    shared. This function only answers "what did this engine do and burn".
    """
    baseline = target_load_fraction(spec.profile, moment)
    if baseline > 0.0:
        jitter = rng_for(seed, spec.id, tick_index, "load").gauss(0.0, LOAD_JITTER_RELATIVE)
        load_fraction = max(0.0, min(1.0, baseline * (1.0 + jitter)))
    else:
        load_fraction = 0.0

    running = is_engine_running(load_fraction)

    # A dry tank cannot run, whatever the demand.
    if running and day_tank_level_l <= 0.0:
        running = False
        load_fraction = 0.0

    consumed = 0.0
    runtime_minutes = 0.0
    if running:
        consumed = fuel_consumed_l(spec.kva_rating, spec.power_factor, load_fraction, minutes)
        # Can't burn what isn't there; the engine dies partway through the tick.
        consumed = min(consumed, day_tank_level_l)
        runtime_minutes = minutes
        if day_tank_level_l - consumed <= 0.0:
            running = False
            load_fraction = 0.0

    events: list[EventSample] = []
    if running != was_running:
        events.append(
            EventSample(
                organisation_id=spec.organisation_id,
                generator_id=spec.id,
                tank_id=None,
                event_type=EventType.ENGINE_START if running else EventType.ENGINE_STOP,
                occurred_at=moment,
                volume_l=None,
                fuel_level_l=day_tank_level_l - consumed,
                detail={"load_pct": round(load_fraction * 100, 2)},
            )
        )

    return BurnResult(
        generator_id=spec.id,
        running=running,
        load_fraction=load_fraction,
        consumed_l=consumed,
        runtime_minutes=runtime_minutes,
        events=events,
    )


def generator_reading(
    spec: GeneratorSpec,
    moment: datetime,
    result: BurnResult,
    reported_day_level_l: float,
    rng: random.Random,
) -> ReadingSample:
    """Assemble the generator telemetry row for a tick."""
    latitude, longitude = jitter_position(spec.latitude, spec.longitude, rng)
    capacity = spec.day_tank.capacity_l

    return ReadingSample(
        generator_id=spec.id,
        organisation_id=spec.organisation_id,
        time=moment,
        fuel_level_l=round(reported_day_level_l, 2),
        fuel_level_pct=round((reported_day_level_l / capacity) * 100.0, 2) if capacity else 0.0,
        load_kw=round(load_kw(spec.kva_rating, spec.power_factor, result.load_fraction), 3),
        load_pct=round(result.load_fraction * 100.0, 2),
        engine_running=result.running,
        consumed_l=round(result.consumed_l, 4),
        runtime_minutes=result.runtime_minutes,
        latitude=round(latitude, 7),
        longitude=round(longitude, 7),
    )


def initial_site_state(spec: SiteSpec, start: datetime, seed: int) -> SiteState:
    """Seed tanks partway full so a backfill doesn't start every site brimming."""
    tanks: dict[uuid.UUID, TankState] = {}

    for bulk in spec.bulk_tanks:
        rng = rng_for(seed, bulk.id, 0, "init")
        tanks[bulk.id] = TankState(level_l=bulk.capacity_l * rng.uniform(0.35, 0.95))

    for generator in spec.generators:
        rng = rng_for(seed, generator.day_tank.id, 0, "init")
        tanks[generator.day_tank.id] = TankState(
            level_l=generator.day_tank.capacity_l * rng.uniform(0.45, 0.95)
        )

    return SiteState(
        simulated_at=start,
        tick_index=0,
        tanks=tanks,
        engine_running={generator.id: False for generator in spec.generators},
    )
