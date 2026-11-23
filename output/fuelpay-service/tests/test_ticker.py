"""Live-ticker planning.

`plan_advance` is the part of the ticker that decides how far each site moves,
and it is deliberately pure so the interesting cases — resume, catch-up after
downtime, a site added mid-flight — can be tested without a database or a
clock. The persistence around it is thin by comparison.

`assemble_site_state` is tested here too: it is the seam where the two halves
of the persisted cursor (engine state, tank levels) are stitched back into one
site, and getting it wrong would resume a site from an inconsistent mix.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.models.entities import SiteProfile, TankKind
from app.services.ticker import MAX_CATCHUP_STEPS, assemble_site_state, plan_advance
from app.simulation.engine import GeneratorSpec, SiteSpec, SiteState, TankSpec, TankState
from app.simulation.site import run_site_span

SEED = 20260729
NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
MINUTES = 5

SITE_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
ORG_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
GEN_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DAY_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
BULK_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


def make_spec() -> SiteSpec:
    day = TankSpec(
        id=DAY_ID,
        organisation_id=ORG_ID,
        kind=TankKind.DAY,
        capacity_l=1000.0,
        reorder_threshold_pct=25.0,
    )
    bulk = TankSpec(
        id=BULK_ID,
        organisation_id=ORG_ID,
        kind=TankKind.BULK,
        capacity_l=5000.0,
        reorder_threshold_pct=30.0,
    )
    return SiteSpec(
        id=SITE_ID,
        organisation_id=ORG_ID,
        profile=SiteProfile.TELECOM_TOWER,
        bulk_tanks=(bulk,),
        generators=(
            GeneratorSpec(
                id=GEN_ID,
                organisation_id=ORG_ID,
                kva_rating=100.0,
                power_factor=0.8,
                profile=SiteProfile.TELECOM_TOWER,
                latitude=6.6018,
                longitude=3.3515,
                day_tank=day,
            ),
        ),
    )


def make_state(simulated_at: datetime, tick: int = 0) -> SiteState:
    return SiteState(
        simulated_at=simulated_at,
        tick_index=tick,
        tanks={
            DAY_ID: TankState(level_l=800.0),
            BULK_ID: TankState(level_l=4000.0),
        },
        engine_running={GEN_ID: True},
    )


@dataclass
class FakeCursor:
    """Stands in for a `simulation_state` row."""

    simulated_at: datetime
    tick_index: int = 0
    engine_running: bool = True


def test_advances_to_now_not_by_a_fixed_amount():
    """The target is wall-clock, so a late tick catches up instead of lagging."""
    state = make_state(NOW - timedelta(minutes=37))
    plan = plan_advance(make_spec(), state, NOW, MINUTES, SEED)

    assert plan is not None
    assert plan.until == NOW
    assert not plan.clamped


def test_no_work_when_already_current():
    """Ticking more often than the simulated step must not rewind or duplicate."""
    assert plan_advance(make_spec(), make_state(NOW), NOW, MINUTES, SEED) is None


def test_no_work_when_cursor_is_ahead_of_now():
    """A cursor past `now` — clock skew, or a manual tick moments ago — is left alone."""
    state = make_state(NOW + timedelta(minutes=1))
    assert plan_advance(make_spec(), state, NOW, MINUTES, SEED) is None


def test_new_site_starts_one_step_back():
    """A site added after the backfill emits immediately.

    Resuming it from its commissioning date would instead dump months of
    history onto a live tick.
    """
    plan = plan_advance(make_spec(), None, NOW, MINUTES, SEED)

    assert plan is not None
    assert plan.state.simulated_at == NOW - timedelta(minutes=MINUTES)
    assert plan.state.tick_index == 0
    assert plan.until == NOW

    _, readings, _, _ = run_site_span(plan.spec, plan.state, plan.until, MINUTES, SEED)
    assert len(readings) == 1


def test_long_downtime_is_capped_and_flagged():
    """Catch-up is spread over ticks rather than blocking on one huge span."""
    behind = timedelta(minutes=MINUTES * MAX_CATCHUP_STEPS * 3)
    plan = plan_advance(make_spec(), make_state(NOW - behind), NOW, MINUTES, SEED)

    assert plan is not None
    assert plan.clamped
    assert plan.until < NOW
    assert plan.until == plan.state.simulated_at + timedelta(minutes=MINUTES * MAX_CATCHUP_STEPS)


def test_capped_catch_up_converges():
    """Repeated capped ticks reach the present rather than falling further behind."""
    spec = make_spec()
    state = make_state(NOW - timedelta(minutes=MINUTES * MAX_CATCHUP_STEPS * 2 + 15))

    for _ in range(5):
        plan = plan_advance(spec, state, NOW, MINUTES, SEED)
        if plan is None:
            break
        state, _, _, _ = run_site_span(spec, plan.state, plan.until, MINUTES, SEED)

    assert state.simulated_at >= NOW


def test_resumed_ticks_do_not_repeat_the_random_stream():
    """tick_index carries across ticks; reusing it would replay the same noise."""
    spec = make_spec()
    state = make_state(NOW - timedelta(minutes=MINUTES * 3), tick=41)

    plan = plan_advance(spec, state, NOW, MINUTES, SEED)
    assert plan is not None

    next_state, readings, _, _ = run_site_span(spec, plan.state, plan.until, MINUTES, SEED)

    assert next_state.tick_index == 41 + len(readings)
    assert len({reading.time for reading in readings}) == len(readings)


def test_consecutive_ticks_produce_a_contiguous_series():
    """No gap and no overlap at the seam between two ticks."""
    spec = make_spec()
    state = make_state(NOW - timedelta(minutes=MINUTES * 4))

    first_plan = plan_advance(spec, state, NOW, MINUTES, SEED)
    assert first_plan is not None
    state, first_readings, _, _ = run_site_span(
        spec, first_plan.state, first_plan.until, MINUTES, SEED
    )

    later = NOW + timedelta(minutes=MINUTES * 4)
    second_plan = plan_advance(spec, state, later, MINUTES, SEED)
    assert second_plan is not None
    _, second_readings, _, _ = run_site_span(
        spec, second_plan.state, second_plan.until, MINUTES, SEED
    )

    times = [reading.time for reading in first_readings + second_readings]
    assert times == sorted(times)
    assert len(set(times)) == len(times)
    gaps = {b - a for a, b in zip(times, times[1:], strict=False)}
    assert gaps == {timedelta(minutes=MINUTES)}


class TestAssembleSiteState:
    def test_rebuilds_a_site_from_both_halves(self):
        spec = make_spec()
        cursors = {GEN_ID: FakeCursor(simulated_at=NOW, tick_index=7)}
        tanks = {DAY_ID: TankState(level_l=600.0), BULK_ID: TankState(level_l=3000.0)}

        state = assemble_site_state(spec, cursors, tanks)

        assert state is not None
        assert state.simulated_at == NOW
        assert state.tick_index == 7
        assert state.tanks[DAY_ID].level_l == 600.0
        assert state.tanks[BULK_ID].level_l == 3000.0
        assert state.engine_running[GEN_ID] is True

    def test_never_simulated_site_is_new(self):
        assert assemble_site_state(make_spec(), {}, {}) is None

    def test_missing_tank_level_is_treated_as_new(self):
        """A half-persisted site must not resume from a mix of fresh and stale
        rows — that would silently invent a level for the missing tank."""
        spec = make_spec()
        cursors = {GEN_ID: FakeCursor(simulated_at=NOW)}
        tanks = {DAY_ID: TankState(level_l=600.0)}  # bulk absent

        assert assemble_site_state(spec, cursors, tanks) is None

    def test_oldest_cursor_anchors_the_site(self):
        """A generator added mid-flight must not drag the site forward past
        history its siblings have not generated yet."""
        spec = make_spec()
        second_gen = uuid.UUID("77777777-7777-7777-7777-777777777777")
        spec = SiteSpec(
            id=spec.id,
            organisation_id=spec.organisation_id,
            profile=spec.profile,
            bulk_tanks=spec.bulk_tanks,
            generators=(
                spec.generators[0],
                GeneratorSpec(
                    id=second_gen,
                    organisation_id=ORG_ID,
                    kva_rating=50.0,
                    power_factor=0.8,
                    profile=SiteProfile.TELECOM_TOWER,
                    latitude=6.6018,
                    longitude=3.3515,
                    day_tank=spec.generators[0].day_tank,
                ),
            ),
        )
        cursors = {
            GEN_ID: FakeCursor(simulated_at=NOW - timedelta(hours=2), tick_index=3),
            second_gen: FakeCursor(simulated_at=NOW, tick_index=99),
        }
        tanks = {DAY_ID: TankState(level_l=600.0), BULK_ID: TankState(level_l=3000.0)}

        state = assemble_site_state(spec, cursors, tanks)

        assert state is not None
        assert state.simulated_at == NOW - timedelta(hours=2)
        assert state.tick_index == 3
