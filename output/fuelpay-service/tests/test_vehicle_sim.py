"""Tractor simulation.

A month of one machine runs in well under two seconds, so the properties are
checked over real spans rather than hand-built single steps: determinism,
fuel conservation, field work staying in the field, and each incident kind
actually being produced when its probability is forced to one.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.models.entities import EventType, VehicleOperation
from app.simulation.field import FieldGeometry, contains
from app.simulation.vehicle import (
    OPERATIONS,
    VehicleSpec,
    fuel_rate_lph,
    initial_vehicle_state,
    run_vehicle_span,
)
from app.tuning import DEFAULT_VEHICLE, VehicleTuning

SEED = 20260729
END = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

SPEC = VehicleSpec(
    id=uuid.UUID("77777777-7777-7777-7777-777777777777"),
    organisation_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
    engine_kw=90.0,
    tank_capacity_l=250.0,
    yard_latitude=9.05,
    yard_longitude=7.45,
    field=FieldGeometry(9.07, 7.47, width_m=400, length_m=600, heading_deg=30),
    primary_operation=VehicleOperation.PLOUGHING,
)

NEVER = VehicleTuning(
    siphon_probability_per_day=0,
    return_line_probability=0,
    short_fill_probability=0,
    after_hours_probability=0,
    off_field_probability=0,
    heavy_day_probability=0,
)


def run(days: float, tuning: VehicleTuning = DEFAULT_VEHICLE, spec: VehicleSpec = SPEC):
    start = END - timedelta(days=days)
    return run_vehicle_span(spec, initial_vehicle_state(spec, start, SEED), END, SEED, tuning)


@pytest.fixture(scope="module")
def month():
    return run(30)


def types(events) -> set[EventType]:
    return {event.event_type for event in events}


def test_deterministic(month):
    assert run(30) == month


def test_resume_matches_one_long_run():
    """Stopping and resuming must not change the data — the live ticker
    resumes every five minutes from persisted state."""
    start = END - timedelta(days=4)
    whole = run_vehicle_span(SPEC, initial_vehicle_state(SPEC, start, SEED), END, SEED)

    state = initial_vehicle_state(SPEC, start, SEED)
    readings, events = [], []
    moment = start
    while moment < END:
        moment = min(moment + timedelta(hours=7), END)
        state, r, e = run_vehicle_span(SPEC, state, moment, SEED)
        readings += r
        events += e

    assert readings == whole[1]
    assert events == whole[2]


def test_fuel_level_within_tank(month):
    _, readings, _ = month
    assert all(0.0 <= r.fuel_level_l <= SPEC.tank_capacity_l for r in readings)


def test_fuel_conservation():
    """With no incidents, end level = start + refuels - engine-reported burn."""
    start_state = initial_vehicle_state(SPEC, END - timedelta(days=10), SEED)
    state, readings, events = run_vehicle_span(SPEC, start_state, END, SEED, NEVER)
    refuelled = sum(e.volume_l for e in events if e.event_type == EventType.REFILL)
    # consumed_l is only on emitted readings, and while the engine runs every
    # minute is emitted, so this is the whole burn.
    burned = sum(r.consumed_l for r in readings)
    expected = start_state.fuel_level_l + refuelled - burned
    assert state.fuel_level_l == pytest.approx(expected, abs=1.0)


def test_field_work_stays_in_field(month):
    _, readings, _ = month
    working = [r for r in readings if r.area_ha > 0]
    assert working, "a month should include field work"
    # GPS jitter is a few metres; the margin covers it.
    assert all(contains(SPEC.field, r.latitude, r.longitude, margin_m=15) for r in working)


def test_work_happens_in_working_hours_only(month):
    _, readings, _ = month
    for reading in readings:
        if reading.area_ha > 0:
            local_hour = (reading.time + timedelta(hours=SPEC.utc_offset_hours)).hour
            assert SPEC.working_hours_start <= local_hour < SPEC.working_hours_end


def test_engine_hours_monotonic(month):
    _, readings, _ = month
    hours = [r.engine_hours for r in readings]
    assert hours == sorted(hours)


def test_readings_every_minute_while_running(month):
    """After any running sample the next arrives a minute later: either the
    engine is still on, or it stopped and the stop itself is reported."""
    _, readings, _ = month
    gaps = {
        (b.time - a.time).total_seconds()
        for a, b in zip(readings, readings[1:], strict=False)
        if a.engine_on
    }
    assert gaps == {60.0}


def test_quiet_tuning_has_no_incidents():
    _, _, events = run(20, NEVER)
    assert not types(events) & {
        EventType.SUSPECTED_DRAIN,
        EventType.SHORT_FILL,
        EventType.MISUSE,
        EventType.OVERCONSUMPTION,
    }


def test_forced_siphon():
    tuning = replace(NEVER, siphon_probability_per_day=1.0)
    _, _, events = run(5, tuning)
    drains = [e for e in events if e.event_type == EventType.SUSPECTED_DRAIN]
    assert drains
    assert all(e.volume_l < 0 for e in drains)
    assert all(e.vehicle_id == SPEC.id and e.tank_id is None for e in drains)


def test_forced_short_fill_reconciles():
    tuning = replace(NEVER, short_fill_probability=1.0)
    _, _, events = run(10, tuning)
    shorts = [e for e in events if e.event_type == EventType.SHORT_FILL]
    assert shorts
    for event in shorts:
        assert event.volume_l < 0
        billed, measured = event.detail["billed_l"], event.detail["measured_l"]
        assert measured < billed
        assert billed - measured == pytest.approx(-event.volume_l, abs=0.2)


def test_forced_return_line_theft():
    tuning = replace(NEVER, return_line_probability=1.0)
    _, _, events = run(10, tuning)
    flagged = [
        e
        for e in events
        if e.event_type == EventType.OVERCONSUMPTION and e.detail["kind"] == "return_line"
    ]
    assert flagged
    for event in flagged:
        assert event.detail["level_drop_l"] > event.detail["engine_reported_l"]


def test_forced_misuse_kinds():
    tuning = replace(NEVER, after_hours_probability=1.0, off_field_probability=1.0)
    _, readings, events = run(10, tuning)
    kinds = {e.detail["kind"] for e in events if e.event_type == EventType.MISUSE}
    assert kinds == {"after_hours", "off_field"}
    # An after-hours trip really leaves the yard after the working day.
    evening = [
        r
        for r in readings
        if r.speed_kmh > 1
        and (r.time + timedelta(hours=SPEC.utc_offset_hours)).hour >= SPEC.working_hours_end
    ]
    assert evening


def test_heavy_days_breach_quota():
    tuning = replace(NEVER, heavy_day_probability=1.0)
    _, _, events = run(10, tuning)
    quota = [
        e
        for e in events
        if e.event_type == EventType.OVERCONSUMPTION and e.detail["kind"] == "quota"
    ]
    assert quota
    for event in quota:
        assert event.detail["l_per_ha"] > event.detail["quota_l_per_ha"]


def test_normal_days_stay_within_quota():
    """Ordinary efficiency must not trip the quota alarm, or every day would."""
    _, _, events = run(20, NEVER)
    assert not any(
        e.event_type == EventType.OVERCONSUMPTION and e.detail["kind"] == "quota" for e in events
    )


def test_fuel_rate_plausible():
    # A 90 kW tractor ploughing burns roughly 15-25 L/h; idle a few L/h.
    plough = fuel_rate_lph(90, OPERATIONS[VehicleOperation.PLOUGHING].load)
    assert 15 <= plough <= 25
    assert 2 <= fuel_rate_lph(90, 0.12) <= 7
    assert fuel_rate_lph(90, 0.0) == 0.0
