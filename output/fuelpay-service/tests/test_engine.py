"""Simulation stepper behaviour.

These tests guard the properties the rest of the system relies on: that the
stepper is deterministic, that fuel is conserved across both storage tiers, and
that the discrete events downstream consumers bill and alert on are actually
emitted.

The two-tier cases carry most of the weight. Fuel reaching an engine now
crosses two tanks and three hops, and each hop is somewhere fuel can go missing
in the real world — so each hop gets asserted on directly.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.entities import EventType, SiteProfile, TankKind
from app.simulation.consumption import fuel_consumed_l
from app.simulation.engine import (
    GPS_JITTER_METRES,
    METRES_PER_DEGREE_LAT,
    GeneratorSpec,
    SiteSpec,
    SiteState,
    TankSpec,
    TankState,
    initial_site_state,
)
from app.simulation.site import run_site_span, step_site
from app.tuning import DeliveryTuning, RefillWindow, SensorTuning, TheftTuning

SEED = 20260729

# Fixed UUIDs: the RNG is keyed on entity id, so random ones would make every
# assertion below depend on which id happened to be drawn.
SITE_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
ORG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
GEN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DAY_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
BULK_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
BULK_ID_2 = uuid.UUID("66666666-6666-6666-6666-666666666666")

NOON = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
MIDNIGHT = datetime(2026, 7, 29, 0, 0, tzinfo=UTC)
NIGHT = datetime(2026, 7, 29, 2, 0, tzinfo=UTC)

# Signal dropout is a per-day probability scaled by the tick length. 1440 makes
# a 1-minute slice certain, so any tick length forces the branch.
ALWAYS_DROP = SensorTuning(dropout_probability_per_day=1440.0)
NEVER_DROP = SensorTuning(dropout_probability_per_day=0.0)
ALWAYS_SHORT = DeliveryTuning(short_probability=1.0)
NEVER_STEAL = TheftTuning(probability_per_day=0.0)


def make_site(
    profile: SiteProfile = SiteProfile.TELECOM_TOWER,
    kva: float = 100.0,
    day_capacity: float = 1000.0,
    day_threshold_pct: float = 25.0,
    bulk_capacity: float = 5000.0,
    bulk_threshold_pct: float = 30.0,
    bulk_count: int = 1,
) -> SiteSpec:
    day = TankSpec(
        id=DAY_ID,
        organisation_id=ORG_ID,
        kind=TankKind.DAY,
        capacity_l=day_capacity,
        reorder_threshold_pct=day_threshold_pct,
    )
    bulk_ids = (BULK_ID, BULK_ID_2)
    bulks = tuple(
        TankSpec(
            id=bulk_ids[index],
            organisation_id=ORG_ID,
            kind=TankKind.BULK,
            capacity_l=bulk_capacity,
            reorder_threshold_pct=bulk_threshold_pct,
        )
        for index in range(bulk_count)
    )
    generator = GeneratorSpec(
        id=GEN_ID,
        organisation_id=ORG_ID,
        kva_rating=kva,
        power_factor=0.8,
        profile=profile,
        latitude=6.6018,
        longitude=3.3515,
        day_tank=day,
    )
    return SiteSpec(
        id=SITE_ID,
        organisation_id=ORG_ID,
        profile=profile,
        bulk_tanks=bulks,
        generators=(generator,),
    )


def make_state(
    moment: datetime,
    day_level: float,
    bulk_level: float = 4000.0,
    bulk_level_2: float = 4000.0,
    running: bool = True,
    tick: int = 0,
    day_drain: float = 0.0,
    bulk_drain: float = 0.0,
    day_tank_state: TankState | None = None,
    bulk_tank_state: TankState | None = None,
) -> SiteState:
    return SiteState(
        simulated_at=moment,
        tick_index=tick,
        tanks={
            DAY_ID: day_tank_state
            or TankState(level_l=day_level, pending_drain_l=day_drain),
            BULK_ID: bulk_tank_state
            or TankState(level_l=bulk_level, pending_drain_l=bulk_drain),
            BULK_ID_2: TankState(level_l=bulk_level_2),
        },
        engine_running={GEN_ID: running},
    )


def _step(spec, state, minutes=5.0, **kwargs):
    """step_site with the noisy subsystems silenced unless a test wants them."""
    options = {
        "theft": NEVER_STEAL,
        "sensor": NEVER_DROP,
        **kwargs,
    }
    return step_site(spec, state, minutes, SEED, **options)


def day_reading(result):
    return next((r for r in result.tank_readings if r.tank_id == DAY_ID), None)


def bulk_reading(result):
    return next((r for r in result.tank_readings if r.tank_id == BULK_ID), None)


def events_of(result, event_type):
    return [e for e in result.events if e.event_type == event_type]


class TestDeterminism:
    def test_same_inputs_produce_identical_output(self):
        spec = make_site()
        state = make_state(NOON, 800.0)

        first = step_site(spec, state, 5.0, SEED)
        second = step_site(spec, state, 5.0, SEED)

        assert first.state == second.state
        assert first.readings == second.readings
        assert first.tank_readings == second.tank_readings
        assert first.events == second.events

    def test_different_seeds_diverge(self):
        spec = make_site()
        state = make_state(NOON, 800.0)

        assert (
            step_site(spec, state, 5.0, SEED).readings[0]
            != step_site(spec, state, 5.0, SEED + 1).readings[0]
        )

    def test_tick_index_advances_the_stream(self):
        spec = make_site()
        at_0 = _step(spec, make_state(NOON, 800.0, tick=0))
        at_1 = _step(spec, make_state(NOON, 800.0, tick=1))

        # Same physical state, different tick — the noise must differ, or a
        # resumed run would replay the random stream it already consumed.
        assert at_0.readings[0].fuel_level_l != at_1.readings[0].fuel_level_l


class TestFuelConservation:
    def test_running_engine_burns_from_its_day_tank(self):
        spec = make_site()
        result = _step(spec, make_state(NOON, 800.0))

        assert result.readings[0].engine_running
        assert result.state.tanks[DAY_ID].level_l < 800.0
        assert result.readings[0].consumed_l > 0.0

    def test_burn_does_not_touch_bulk_storage(self):
        """An engine draws from its day tank only; bulk moves by transfer."""
        spec = make_site()
        result = _step(spec, make_state(NOON, 800.0, bulk_level=4000.0))

        assert result.state.tanks[BULK_ID].level_l == pytest.approx(4000.0)

    def test_consumed_matches_the_level_drop(self):
        spec = make_site()
        state = make_state(NOON, 800.0)
        result = _step(spec, state)

        burned = 800.0 - result.state.tanks[DAY_ID].level_l
        assert burned == pytest.approx(result.readings[0].consumed_l, abs=1e-4)

    def test_consumed_matches_the_physics_formula(self):
        spec = make_site()
        result = _step(spec, make_state(NOON, 800.0))
        expected = fuel_consumed_l(
            100.0, 0.8, result.readings[0].load_pct / 100.0, 5.0
        )
        assert result.readings[0].consumed_l == pytest.approx(expected, abs=1e-3)

    def test_stopped_engine_burns_nothing(self):
        # Residential profile is off at 02:00.
        spec = make_site(profile=SiteProfile.RESIDENTIAL, kva=30.0)
        result = _step(spec, make_state(NIGHT, 900.0, running=False))

        assert not result.readings[0].engine_running
        assert result.readings[0].consumed_l == 0.0
        assert result.state.tanks[DAY_ID].level_l == pytest.approx(900.0)

    def test_dry_day_tank_stops_the_engine(self):
        spec = make_site()
        # No bulk behind it either, or a transfer would refill it mid-tick.
        result = _step(spec, make_state(NOON, 0.0, bulk_level=0.0, bulk_level_2=0.0))

        assert not result.readings[0].engine_running
        assert result.readings[0].load_kw == 0.0
        assert result.state.tanks[DAY_ID].level_l >= 0.0

    def test_levels_never_leave_physical_bounds(self):
        """Two weeks of ticking, checking the invariant on both tiers."""
        spec = make_site()
        state = initial_site_state(spec, MIDNIGHT, SEED)
        until = MIDNIGHT + timedelta(days=14)

        while state.simulated_at < until:
            result = step_site(spec, state, 5.0, SEED)
            state = result.state
            assert 0.0 <= state.tanks[DAY_ID].level_l <= 1000.0
            assert 0.0 <= state.tanks[BULK_ID].level_l <= 5000.0
            for reading in result.tank_readings:
                assert reading.level_l >= 0.0
            assert 0.0 <= result.readings[0].load_pct <= 100.0


class TestTransfer:
    def test_day_tank_below_threshold_pulls_from_bulk(self):
        spec = make_site()
        result = _step(spec, make_state(NOON, 200.0, bulk_level=4000.0))

        transfers = events_of(result, EventType.TRANSFER)
        assert len(transfers) == 1
        assert transfers[0].volume_l > 0.0
        assert transfers[0].tank_id == BULK_ID
        # The event names the destination so a bulk drop is attributable.
        assert transfers[0].detail["to_tank_id"] == str(DAY_ID)
        assert result.state.tanks[DAY_ID].level_l > 200.0
        assert result.state.tanks[BULK_ID].level_l < 4000.0

    def test_transfer_conserves_fuel_across_the_two_tiers(self):
        spec = make_site()
        state = make_state(NOON, 200.0, bulk_level=4000.0)
        result = _step(spec, state)

        moved = 4000.0 - result.state.tanks[BULK_ID].level_l
        gained = result.state.tanks[DAY_ID].level_l - 200.0
        burned = result.readings[0].consumed_l
        # Everything that left bulk arrived in the day tank, less what burned.
        # Tolerance is set by `consumed_l` being rounded to 4dp on the reading,
        # not by any slack in the conservation itself.
        assert gained == pytest.approx(moved - burned, abs=1e-3)

    def test_transfer_is_rate_limited_by_the_pump(self):
        """A pump moves a bounded volume per minute, so a big day tank fills
        over several ticks rather than teleporting to full."""
        spec = make_site()
        result = _step(spec, make_state(NOON, 100.0, bulk_level=4000.0))

        # 40 L/min x 5 min = 200 L this tick, not the ~850 L needed to fill.
        transfer = events_of(result, EventType.TRANSFER)[0]
        assert transfer.volume_l == pytest.approx(200.0)

    def test_full_day_tank_pulls_nothing(self):
        spec = make_site()
        result = _step(spec, make_state(NOON, 950.0, bulk_level=4000.0))

        assert not events_of(result, EventType.TRANSFER)

    def test_transfer_draws_from_several_bulk_tanks(self):
        """A site may run more than one bulk vessel; a transfer spans them."""
        # Threshold 0 keeps a tanker out of it: an almost-empty bulk tank would
        # otherwise take an emergency delivery in the same tick and mask the
        # drawdown this test is about.
        spec = make_site(bulk_count=2, bulk_threshold_pct=0.0)
        # First tank cannot cover the 200 L the pump will move.
        result = _step(spec, make_state(NOON, 100.0, bulk_level=50.0, bulk_level_2=4000.0))

        transfers = events_of(result, EventType.TRANSFER)
        assert {e.tank_id for e in transfers} == {BULK_ID, BULK_ID_2}
        assert sum(e.volume_l for e in transfers) == pytest.approx(200.0)
        # Drained the first dry, then took the remainder from the second.
        by_tank = {e.tank_id: e.volume_l for e in transfers}
        assert by_tank[BULK_ID] == pytest.approx(50.0)
        assert by_tank[BULK_ID_2] == pytest.approx(150.0)
        assert result.state.tanks[BULK_ID].level_l == pytest.approx(0.0)

    def test_exhausted_bulk_raises_low_fuel(self):
        """The day tank running down with nothing behind it is the alarm."""
        spec = make_site(bulk_count=1)
        result = _step(spec, make_state(NOON, 200.0, bulk_level=0.0))

        low = events_of(result, EventType.LOW_FUEL)
        assert len(low) == 1
        assert low[0].detail["bulk_exhausted"] is True
        assert not events_of(result, EventType.TRANSFER)


class TestDelivery:
    def test_bulk_below_threshold_is_delivered_in_the_window(self):
        spec = make_site()  # bulk threshold 30% of 5000 L = 1500 L
        result = _step(spec, make_state(NOON, 900.0, bulk_level=1000.0))

        deliveries = events_of(result, EventType.DELIVERY)
        assert len(deliveries) == 1
        assert deliveries[0].volume_l > 0.0
        assert deliveries[0].tank_id == BULK_ID
        # A delivery belongs to the site, not to any one generator.
        assert deliveries[0].generator_id is None

    def test_no_routine_delivery_outside_the_window(self):
        spec = make_site()
        result = _step(spec, make_state(NIGHT, 900.0, bulk_level=1000.0))

        assert not events_of(result, EventType.DELIVERY)

    def test_critical_bulk_is_delivered_at_any_hour(self):
        spec = make_site()
        result = _step(spec, make_state(NIGHT, 900.0, bulk_level=100.0))

        deliveries = events_of(result, EventType.DELIVERY)
        assert len(deliveries) == 1
        assert deliveries[0].detail["emergency"] is True

    def test_delivery_never_overfills(self):
        spec = make_site()
        result = _step(spec, make_state(NOON, 900.0, bulk_level=1000.0))
        assert result.state.tanks[BULK_ID].level_l <= 5000.0

    def test_short_delivery_is_flagged_and_signed_negative(self):
        """The fraud the bulk sensor exists to catch: billed for more than was
        dropped. Without a sensor on the receiving tank nobody can prove it."""
        spec = make_site()
        result = _step(spec, make_state(NOON, 900.0, bulk_level=1000.0), delivery=ALWAYS_SHORT)

        short = events_of(result, EventType.SHORT_DELIVERY)
        assert len(short) == 1
        assert short[0].volume_l < 0.0
        assert short[0].detail["delivered_l"] < short[0].detail["billed_l"]
        assert short[0].detail["shortfall_pct"] > 0.0

    def test_honest_delivery_raises_no_shortfall(self):
        spec = make_site()
        honest = DeliveryTuning(short_probability=0.0)
        result = _step(spec, make_state(NOON, 900.0, bulk_level=1000.0), delivery=honest)

        assert events_of(result, EventType.DELIVERY)
        assert not events_of(result, EventType.SHORT_DELIVERY)

    def test_delivered_volume_matches_the_level_rise(self):
        spec = make_site()
        state = make_state(NOON, 900.0, bulk_level=1000.0)
        result = _step(spec, state, delivery=ALWAYS_SHORT)

        delivery = events_of(result, EventType.DELIVERY)[0]
        # Transfers may also have drawn on the tank this tick.
        transferred = sum(e.volume_l for e in events_of(result, EventType.TRANSFER))
        rise = result.state.tanks[BULK_ID].level_l - 1000.0
        assert rise == pytest.approx(delivery.volume_l - transferred, abs=1e-6)


class TestTheft:
    def test_pending_drain_removes_fuel_and_reports_it(self):
        spec = make_site()
        state = make_state(NIGHT, 800.0, running=False, day_drain=300.0)
        result = _step(spec, state)

        drains = events_of(result, EventType.SUSPECTED_DRAIN)
        assert len(drains) == 1
        # Signed negative so a SUM over events nets out against deliveries.
        assert drains[0].volume_l < 0.0
        assert drains[0].detail["ground_truth"] is True
        assert drains[0].detail["tank_kind"] == "DAY"

    def test_bulk_storage_can_be_siphoned(self):
        """Bulk is the softer and more valuable target, so it must be modelled."""
        spec = make_site()
        state = make_state(NIGHT, 900.0, bulk_level=4000.0, running=False, bulk_drain=500.0)
        result = _step(spec, state)

        drains = [
            e for e in events_of(result, EventType.SUSPECTED_DRAIN) if e.tank_id == BULK_ID
        ]
        assert len(drains) == 1
        assert drains[0].detail["tank_kind"] == "BULK"
        assert result.state.tanks[BULK_ID].level_l < 4000.0

    def test_bulk_theft_is_not_deterred_by_a_running_engine(self):
        """A 24/7 site — every bank branch and telecom tower — would otherwise
        be immune to bulk theft, which is exactly the population the product
        exists to protect."""
        spec = make_site()
        always = TheftTuning(
            probability_per_day=2000.0, window_start_hour=0, window_end_hour=24
        )
        result = _step(spec, make_state(NOON, 900.0, running=True), theft=always)

        drains = [
            e for e in events_of(result, EventType.SUSPECTED_DRAIN) if e.tank_id == BULK_ID
        ]
        assert len(drains) == 1

    def test_day_tank_theft_is_deterred_by_its_own_engine(self):
        """The set is noisy, hot and usually attended; the day tank feeding it
        is not where a thief starts."""
        spec = make_site()
        always = TheftTuning(
            probability_per_day=2000.0, window_start_hour=0, window_end_hour=24
        )
        result = _step(spec, make_state(NOON, 900.0, running=True), theft=always)

        assert not [
            e for e in events_of(result, EventType.SUSPECTED_DRAIN) if e.tank_id == DAY_ID
        ]

    def test_siphon_is_rate_limited_across_ticks(self):
        """A 300 L theft cannot complete in one 5-minute tick."""
        spec = make_site()
        state = make_state(NIGHT, 800.0, running=False, day_drain=300.0)
        result = _step(spec, state)

        # 2% of a 1000 L tank per minute x 5 minutes = 100 L this tick.
        drain = events_of(result, EventType.SUSPECTED_DRAIN)[0]
        assert drain.volume_l == pytest.approx(-100.0)
        assert result.state.tanks[DAY_ID].pending_drain_l == pytest.approx(200.0)

    def test_siphon_cannot_take_more_than_is_present(self):
        spec = make_site()
        state = make_state(
            NIGHT, 30.0, bulk_level=0.0, bulk_level_2=0.0, running=False, day_drain=500.0
        )
        result = _step(spec, state)

        assert result.state.tanks[DAY_ID].level_l >= 0.0


class TestSensorSignal:
    def test_a_tank_with_no_signal_emits_no_reading(self):
        """Absence of rows is how a gap is represented. Inventing a value for
        an unobserved period is the error that would let fuel vanish unseen."""
        spec = make_site()
        result = _step(spec, make_state(NOON, 800.0), sensor=ALWAYS_DROP)

        assert result.tank_readings == []
        assert events_of(result, EventType.SIGNAL_LOSS)

    def test_generator_telemetry_survives_a_fuel_sensor_dropout(self):
        """The engine is instrumented separately: losing the fuel probe blinds
        the level, not the load."""
        spec = make_site()
        result = _step(spec, make_state(NOON, 800.0), sensor=ALWAYS_DROP)

        assert len(result.readings) == 1
        assert result.readings[0].load_kw > 0.0

    def test_signal_stays_down_for_the_drawn_duration(self):
        spec = make_site()
        state = make_state(NOON, 800.0)
        result = _step(spec, state, sensor=ALWAYS_DROP)
        out_ticks = result.state.tanks[DAY_ID].signal_out_ticks
        assert out_ticks >= 2

        # Stepping on with a normal sensor must not resurrect it early.
        state = result.state
        for _ in range(out_ticks - 1):
            result = _step(spec, state)
            assert day_reading(result) is None
            state = result.state

        assert day_reading(_step(spec, state)) is not None

    def test_reconnect_flags_fuel_that_went_missing_in_the_dark(self):
        spec = make_site()
        # Restores this tick, having lost 300 L that nothing accounts for.
        blind = TankState(
            level_l=500.0,
            signal_out_ticks=1,
            level_at_signal_loss_l=800.0,
            accounted_outflow_l=0.0,
        )
        result = _step(spec, make_state(NOON, 500.0, day_tank_state=blind))

        assert events_of(result, EventType.SIGNAL_RESTORED)
        losses = events_of(result, EventType.UNVERIFIED_LOSS)
        assert len(losses) == 1
        assert losses[0].volume_l < 0.0
        assert losses[0].detail["unexplained_l"] > 0.0

    def test_reconnect_after_ordinary_consumption_raises_nothing(self):
        """A gap that spans a normal night's burn is not an incident."""
        spec = make_site()
        blind = TankState(
            level_l=500.0,
            signal_out_ticks=1,
            level_at_signal_loss_l=800.0,
            # Every one of those 300 L is accounted for by burn.
            accounted_outflow_l=300.0,
        )
        result = _step(spec, make_state(NOON, 500.0, day_tank_state=blind))

        assert events_of(result, EventType.SIGNAL_RESTORED)
        assert not events_of(result, EventType.UNVERIFIED_LOSS)

    def test_unverified_loss_is_not_reported_as_a_drain(self):
        """Nobody was watching, so it cannot be attributed to theft. Calling it
        SUSPECTED_DRAIN would assert more than the data supports."""
        spec = make_site()
        blind = TankState(
            level_l=400.0,
            signal_out_ticks=1,
            level_at_signal_loss_l=900.0,
            accounted_outflow_l=0.0,
        )
        result = _step(spec, make_state(NOON, 400.0, day_tank_state=blind))

        assert events_of(result, EventType.UNVERIFIED_LOSS)
        assert not events_of(result, EventType.SUSPECTED_DRAIN)


class TestMeasurement:
    def test_reported_level_differs_from_the_truth(self):
        """Sensor noise is the point: consumers must not get clean data."""
        spec = make_site()
        samples = [_step(spec, make_state(NOON, 800.0, tick=t)) for t in range(20)]
        assert any(
            abs(day_reading(s).level_l - s.state.tanks[DAY_ID].level_l) > 0.01
            for s in samples
            if day_reading(s)
        )

    def test_reported_level_stays_close_to_the_truth(self):
        """Noisy, but not wrong — within a few percent of capacity."""
        spec = make_site()
        for tick in range(50):
            result = _step(spec, make_state(NOON, 800.0, tick=tick))
            reading = day_reading(result)
            assert abs(reading.level_l - result.state.tanks[DAY_ID].level_l) < 50.0

    def test_level_is_quantised(self):
        spec = make_site()
        for tick in range(20):
            level = day_reading(_step(spec, make_state(NOON, 800.0, tick=tick))).level_l
            assert round(level * 10) == pytest.approx(level * 10, abs=1e-6)

    def test_bulk_reading_reports_its_own_capacity_not_the_day_tank(self):
        spec = make_site()
        result = _step(spec, make_state(NOON, 800.0, bulk_level=2500.0))
        reading = bulk_reading(result)

        # 2500 of 5000 L is 50%, not the 80% the day tank happens to be at.
        assert reading.level_pct == pytest.approx(50.0, abs=2.0)

    def test_gps_stays_within_a_few_metres_of_the_installation(self):
        spec = make_site()
        for tick in range(200):
            reading = _step(spec, make_state(NOON, 800.0, tick=tick)).readings[0]
            north_m = (reading.latitude - 6.6018) * METRES_PER_DEGREE_LAT
            # A generator that appears to move is a bug, not telemetry.
            assert abs(north_m) < GPS_JITTER_METRES * 5


class TestRunSpan:
    def test_produces_one_generator_reading_per_step(self):
        spec = make_site()
        state = initial_site_state(spec, MIDNIGHT, SEED)
        _, readings, _, _ = run_site_span(spec, state, MIDNIGHT + timedelta(days=1), 5.0, SEED)

        assert len(readings) == 288  # 24h / 5min

    def test_tank_readings_never_exceed_one_per_tank_per_step(self):
        """Sparser than generator telemetry: a blind tank contributes nothing."""
        spec = make_site()
        state = initial_site_state(spec, MIDNIGHT, SEED)
        _, _, tank_readings, _ = run_site_span(
            spec, state, MIDNIGHT + timedelta(days=1), 5.0, SEED
        )

        per_tank = [r for r in tank_readings if r.tank_id == DAY_ID]
        assert 0 < len(per_tank) <= 288

    def test_readings_are_strictly_ordered(self):
        spec = make_site()
        state = initial_site_state(spec, MIDNIGHT, SEED)
        _, readings, tank_readings, _ = run_site_span(
            spec, state, MIDNIGHT + timedelta(days=2), 5.0, SEED
        )

        times = [r.time for r in readings]
        assert times == sorted(times)
        assert len(set(times)) == len(times)

        day_times = [r.time for r in tank_readings if r.tank_id == DAY_ID]
        assert day_times == sorted(day_times)
        assert len(set(day_times)) == len(day_times)

    def test_a_week_of_a_telecom_tower_moves_fuel_down_both_tiers(self):
        """End-to-end sanity: a 24/7 tower drains its day tank in days, so a
        week must contain both transfers and a tanker delivery."""
        spec = make_site()
        state = initial_site_state(spec, MIDNIGHT, SEED)
        _, _, _, events = run_site_span(spec, state, MIDNIGHT + timedelta(days=7), 5.0, SEED)

        assert [e for e in events if e.event_type == EventType.TRANSFER]
        assert [e for e in events if e.event_type == EventType.DELIVERY]

    def test_bank_branch_never_fully_shuts_down(self):
        """ATMs, the vault and comms run overnight, so unlike an office the
        branch profile has no zero-load hour."""
        spec = make_site(profile=SiteProfile.BANK_BRANCH, kva=75.0)
        state = initial_site_state(spec, MIDNIGHT, SEED)
        _, readings, _, _ = run_site_span(spec, state, MIDNIGHT + timedelta(days=2), 5.0, SEED)

        assert all(r.load_pct > 0.0 for r in readings)

    def test_residential_profile_cycles_the_engine(self):
        """An estate genset stops overnight, so start/stop pairs must appear."""
        spec = make_site(profile=SiteProfile.RESIDENTIAL, kva=30.0)
        state = initial_site_state(spec, MIDNIGHT, SEED)
        _, _, _, events = run_site_span(spec, state, MIDNIGHT + timedelta(days=3), 5.0, SEED)

        assert [e for e in events if e.event_type == EventType.ENGINE_START]
        assert [e for e in events if e.event_type == EventType.ENGINE_STOP]

    def test_resuming_matches_an_uninterrupted_run(self):
        """Backfill then live-tick must equal one continuous run — this is what
        makes the persisted cursors trustworthy."""
        spec = make_site()
        start = MIDNIGHT
        middle = MIDNIGHT + timedelta(days=1)
        end = MIDNIGHT + timedelta(days=2)

        state = initial_site_state(spec, start, SEED)
        _, whole, whole_tanks, _ = run_site_span(spec, state, end, 5.0, SEED)

        state = initial_site_state(spec, start, SEED)
        state, first, first_tanks, _ = run_site_span(spec, state, middle, 5.0, SEED)
        _, second, second_tanks, _ = run_site_span(spec, state, end, 5.0, SEED)

        assert first + second == whole
        assert first_tanks + second_tanks == whole_tanks


class TestDeliveryWindow:
    def test_window_is_configurable(self):
        spec = make_site()
        all_hours = RefillWindow(start_hour=0, end_hour=24)
        result = _step(spec, make_state(NIGHT, 900.0, bulk_level=1000.0), refill_window=all_hours)

        assert events_of(result, EventType.DELIVERY)
