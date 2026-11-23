"""Configurable incident rates.

The point of moving these out of module constants was to let a demo make
siphons, deliveries and sensor dropouts happen on request. These tests hold
that promise to account: that the knobs actually change behaviour, and that
leaving them alone reproduces exactly what the engine does by default.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.models.entities import EventType, SiteProfile, TankKind
from app.simulation.engine import GeneratorSpec, SiteSpec, SiteState, TankSpec, TankState
from app.simulation.site import step_site
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

SEED = 20260729

# Residential sites are idle mid-morning, and theft needs the engine off.
ENGINE_OFF = datetime(2026, 8, 2, 10, 0, tzinfo=UTC)

ORG_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
GEN_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
DAY_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
BULK_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")

# A daily probability this large makes the per-tick odds exceed 1, so the draw
# always succeeds. Deterministic beats running a thousand ticks and hoping.
ALWAYS = TheftTuning(probability_per_day=2000.0, window_start_hour=0, window_end_hour=24)
NEVER = TheftTuning(probability_per_day=0.0)
NO_DROPOUT = SensorTuning(dropout_probability_per_day=0.0)


def make_spec(
    profile: SiteProfile = SiteProfile.RESIDENTIAL,
    day_capacity: float = 1000.0,
    bulk_capacity: float = 5000.0,
) -> SiteSpec:
    day = TankSpec(
        id=DAY_ID,
        organisation_id=ORG_ID,
        kind=TankKind.DAY,
        capacity_l=day_capacity,
        reorder_threshold_pct=25.0,
    )
    bulk = TankSpec(
        id=BULK_ID,
        organisation_id=ORG_ID,
        kind=TankKind.BULK,
        capacity_l=bulk_capacity,
        reorder_threshold_pct=25.0,
    )
    return SiteSpec(
        id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        organisation_id=ORG_ID,
        profile=profile,
        bulk_tanks=(bulk,),
        generators=(
            GeneratorSpec(
                id=GEN_ID,
                organisation_id=ORG_ID,
                kva_rating=30.0,
                power_factor=0.8,
                profile=profile,
                latitude=7.3775,
                longitude=3.9470,
                day_tank=day,
            ),
        ),
    )


def make_state(moment: datetime, day_level: float, bulk_level: float = 4000.0) -> SiteState:
    return SiteState(
        simulated_at=moment,
        tick_index=0,
        tanks={
            DAY_ID: TankState(level_l=day_level),
            BULK_ID: TankState(level_l=bulk_level),
        },
        engine_running={GEN_ID: False},
    )


def types_of(result):
    return [event.event_type for event in result.events]


def test_raising_theft_probability_produces_a_drain():
    spec = make_spec()
    state = make_state(ENGINE_OFF - timedelta(minutes=5), 800.0)

    result = step_site(spec, state, 5.0, SEED, theft=ALWAYS, sensor=NO_DROPOUT)

    assert EventType.SUSPECTED_DRAIN in types_of(result)
    assert result.state.tanks[DAY_ID].level_l < 800.0


def test_zero_probability_never_drains():
    spec = make_spec()
    state = make_state(ENGINE_OFF, 800.0)

    for _ in range(200):
        result = step_site(spec, state, 5.0, SEED, theft=NEVER, sensor=NO_DROPOUT)
        state = result.state
        assert EventType.SUSPECTED_DRAIN not in types_of(result)


def test_theft_window_gates_the_probability():
    """Raising the odds alone is not enough — the hour window has to allow it.

    This is the trap the config comment warns about: a demo at midday with a
    22:00-04:00 window sees nothing however high the probability goes.
    """
    spec = make_spec()
    state = make_state(ENGINE_OFF, 800.0)

    nocturnal = TheftTuning(probability_per_day=2000.0, window_start_hour=22, window_end_hour=4)
    result = step_site(spec, state, 5.0, SEED, theft=nocturnal, sensor=NO_DROPOUT)

    assert EventType.SUSPECTED_DRAIN not in types_of(result)
    assert result.state.tanks[DAY_ID].level_l == 800.0


def test_theft_volume_fractions_bound_the_siphon():
    spec = make_spec()
    state = make_state(ENGINE_OFF, 1000.0)

    tuning = TheftTuning(
        probability_per_day=2000.0,
        volume_min_fraction=0.10,
        volume_max_fraction=0.10,
        window_start_hour=0,
        window_end_hour=24,
    )
    result = step_site(spec, state, 5.0, SEED, theft=tuning, sensor=NO_DROPOUT)

    # 10% of a 1000 L tank, spread over however many ticks the pump rate needs.
    day = result.state.tanks[DAY_ID]
    total = day.pending_drain_l + (1000.0 - day.level_l)
    assert total == 100.0


def test_widening_the_refill_window_allows_an_overnight_delivery():
    """Bulk under threshold at 03:00 is normally left until morning."""
    spec = make_spec()
    at_0300 = datetime(2026, 8, 2, 3, 0, tzinfo=UTC)
    # Above the 5% emergency line, below the 25% reorder threshold.
    state = make_state(at_0300, 900.0, bulk_level=800.0)

    overnight = step_site(
        spec, state, 5.0, SEED, theft=NEVER, refill_window=DEFAULT_REFILL_WINDOW,
        sensor=NO_DROPOUT,
    )
    assert EventType.DELIVERY not in types_of(overnight)

    always_open = step_site(
        spec, state, 5.0, SEED, theft=NEVER,
        refill_window=RefillWindow(start_hour=0, end_hour=24), sensor=NO_DROPOUT,
    )
    assert EventType.DELIVERY in types_of(always_open)


def test_short_delivery_probability_is_a_knob():
    spec = make_spec()
    state = make_state(ENGINE_OFF, 900.0, bulk_level=800.0)
    open_window = RefillWindow(start_hour=0, end_hour=24)

    honest = step_site(
        spec, state, 5.0, SEED, theft=NEVER, refill_window=open_window,
        delivery=DeliveryTuning(short_probability=0.0), sensor=NO_DROPOUT,
    )
    assert EventType.SHORT_DELIVERY not in types_of(honest)

    crooked = step_site(
        spec, state, 5.0, SEED, theft=NEVER, refill_window=open_window,
        delivery=DeliveryTuning(short_probability=1.0), sensor=NO_DROPOUT,
    )
    assert EventType.SHORT_DELIVERY in types_of(crooked)


def test_short_delivery_tolerance_suppresses_trivial_shortfalls():
    """Measurement slop is not fraud. A tolerance wider than the shortfall
    means no allegation, even though the delivery was still short."""
    spec = make_spec()
    state = make_state(ENGINE_OFF, 900.0, bulk_level=800.0)
    open_window = RefillWindow(start_hour=0, end_hour=24)

    forgiving = DeliveryTuning(
        short_probability=1.0,
        short_min_fraction=0.01,
        short_max_fraction=0.01,
        tolerance_fraction=0.05,
    )
    result = step_site(
        spec, state, 5.0, SEED, theft=NEVER, refill_window=open_window,
        delivery=forgiving, sensor=NO_DROPOUT,
    )

    assert EventType.DELIVERY in types_of(result)
    assert EventType.SHORT_DELIVERY not in types_of(result)


def test_transfer_pump_rate_bounds_what_one_tick_moves():
    spec = make_spec()
    state = make_state(ENGINE_OFF, 100.0, bulk_level=4000.0)

    slow = step_site(
        spec, state, 5.0, SEED, theft=NEVER, sensor=NO_DROPOUT,
        transfer=TransferTuning(pump_rate_lpm=10.0),
    )
    fast = step_site(
        spec, state, 5.0, SEED, theft=NEVER, sensor=NO_DROPOUT,
        transfer=TransferTuning(pump_rate_lpm=100.0),
    )

    slow_moved = 4000.0 - slow.state.tanks[BULK_ID].level_l
    fast_moved = 4000.0 - fast.state.tanks[BULK_ID].level_l
    assert slow_moved == 50.0  # 10 L/min x 5 min
    assert fast_moved == 500.0  # 100 L/min x 5 min


def test_sensor_dropout_probability_is_a_knob():
    spec = make_spec()
    state = make_state(ENGINE_OFF, 900.0)

    never = step_site(spec, state, 5.0, SEED, theft=NEVER, sensor=NO_DROPOUT)
    assert len(never.tank_readings) == 2
    assert EventType.SIGNAL_LOSS not in types_of(never)

    always = step_site(
        spec, state, 5.0, SEED, theft=NEVER,
        sensor=SensorTuning(dropout_probability_per_day=1440.0),
    )
    assert always.tank_readings == []
    assert EventType.SIGNAL_LOSS in types_of(always)


def test_drain_step_count_tracks_the_simulated_step_size():
    """A fixed step count under-drains whenever minutes-per-tick is lowered.

    The pump moves 2% of capacity per simulated *minute*, so halving the step
    size must double the steps or the siphon stops partway — which is what the
    livelier demo profile (1 minute per tick) was silently doing.
    """
    from app.services.simulate import steps_to_drain

    capacity = 250.0
    volume = 120.0

    # 2% of 250 L = 5 L per simulated minute.
    assert steps_to_drain(volume, capacity, minutes_per_step=5.0) == 5  # 25 L/step
    assert steps_to_drain(volume, capacity, minutes_per_step=1.0) == 24  # 5 L/step


def test_drain_step_count_is_bounded():
    from app.services.simulate import MAX_STEPS, steps_to_drain

    assert steps_to_drain(1e9, 250.0, 1.0) == MAX_STEPS
    assert steps_to_drain(0.0, 250.0, 5.0) == 1


def test_defaults_reproduce_the_published_rates():
    """The dataclass defaults are the values the engine used as constants."""
    assert DEFAULT_THEFT.probability_per_day == 0.015
    assert DEFAULT_THEFT.volume_min_fraction == 0.20
    assert DEFAULT_THEFT.volume_max_fraction == 0.40
    assert DEFAULT_THEFT.window_start_hour == 22
    assert DEFAULT_THEFT.window_end_hour == 4
    assert DEFAULT_REFILL_WINDOW.start_hour == 8
    assert DEFAULT_REFILL_WINDOW.end_hour == 17


def test_omitting_tuning_matches_passing_the_defaults():
    """Callers that ignore the new parameters get the default simulation."""
    spec = make_spec()
    state = make_state(ENGINE_OFF, 800.0)

    implicit = step_site(spec, state, 5.0, SEED)
    explicit = step_site(
        spec,
        state,
        5.0,
        SEED,
        theft=DEFAULT_THEFT,
        refill_window=DEFAULT_REFILL_WINDOW,
        delivery=DEFAULT_DELIVERY,
        transfer=DEFAULT_TRANSFER,
        sensor=DEFAULT_SENSOR,
    )

    assert implicit.state == explicit.state
    assert implicit.readings == explicit.readings
    assert implicit.tank_readings == explicit.tank_readings
