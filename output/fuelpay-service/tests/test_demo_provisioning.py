"""Demo-account rules that need no database: coupon validity, domain checks on
what a prospect may create, field geometry, and the redeem rate limiter."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.entities import Coupon
from app.ratelimit import SlidingWindowLimiter
from app.schemas import LocationCreate, TractorCreate
from app.services.provisioning import (
    ProvisioningError,
    coupon_rejection,
    days_left,
    demo_slug,
    generate_coupon_code,
    normalise_code,
    validate_location,
    validate_tractor,
)
from app.simulation.field import (
    FieldGeometry,
    boustrophedon_passes,
    contains,
    field_polygon,
    field_to_latlon,
    haversine_m,
    latlon_to_field,
)

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def coupon(**overrides) -> Coupon:
    values = dict(
        code="ABCD-EFGH",
        max_redemptions=3,
        redemptions_count=0,
        expires_at=None,
        is_active=True,
        demo_duration_days=14,
        max_locations=2,
        max_tractors=3,
        max_generators_per_location=3,
    )
    values.update(overrides)
    return Coupon(**values)


# --- coupons ---


def test_valid_coupon():
    assert coupon_rejection(coupon(), NOW) is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"is_active": False}, "inactive"),
        ({"expires_at": NOW - timedelta(seconds=1)}, "expired"),
        ({"expires_at": NOW}, "expired"),
        ({"redemptions_count": 3}, "exhausted"),
    ],
)
def test_rejected_coupons(overrides, reason):
    assert coupon_rejection(coupon(**overrides), NOW) == reason


def test_unknown_coupon():
    assert coupon_rejection(None, NOW) == "unknown code"


def test_code_normalised_and_generated():
    assert normalise_code("  abcd-efgh ") == "ABCD-EFGH"
    code = generate_coupon_code()
    assert len(code) == 9 and code[4] == "-"
    # No look-alike characters.
    assert not set(code) & set("01IOLU")


def test_demo_slug_never_collides_with_seed():
    slug = demo_slug("Demo")
    assert slug.startswith("demo-demo-") and slug != "demo"
    assert demo_slug("Ádé & Sons Ltd.").startswith("demo-d-sons-ltd-")


def test_days_left_rounds_up():
    assert days_left(NOW + timedelta(days=13, hours=1), NOW) == 14
    assert days_left(NOW + timedelta(minutes=5), NOW) == 1
    assert days_left(NOW - timedelta(minutes=5), NOW) == 0


# --- locations ---


def location(**overrides) -> LocationCreate:
    values = dict(
        name="Lekki Branch",
        latitude=6.44,
        longitude=3.47,
        generators=[{"name": "GEN-1", "kva_rating": 60, "day_tank_capacity_l": 1200}],
        bulk_tanks=[{"capacity_l": 10_000}],
    )
    values.update(overrides)
    return LocationCreate(**values)


def test_valid_location():
    validate_location(location(), max_generators=3)


def test_day_tank_floor_in_schema():
    with pytest.raises(ValidationError):
        location(generators=[{"name": "G", "kva_rating": 60, "day_tank_capacity_l": 500}])


def test_bulk_floor_in_schema():
    with pytest.raises(ValidationError):
        location(bulk_tanks=[{"capacity_l": 3000}])


def test_kva_outside_band_rejected():
    with pytest.raises(ProvisioningError, match="kVA"):
        validate_location(
            location(generators=[{"name": "G", "kva_rating": 45, "day_tank_capacity_l": 1000}]),
            max_generators=3,
        )


def test_generator_limit():
    gens = [{"name": f"G{i}", "kva_rating": 60, "day_tank_capacity_l": 1000} for i in range(4)]
    with pytest.raises(ProvisioningError, match="up to 3"):
        validate_location(location(generators=gens), max_generators=3)


def test_duplicate_generator_names():
    gens = [{"name": "Gen", "kva_rating": 60, "day_tank_capacity_l": 1000}] * 2
    with pytest.raises(ProvisioningError, match="unique"):
        validate_location(location(generators=gens), max_generators=3)


# --- tractors ---


def tractor(**overrides) -> TractorCreate:
    values = dict(
        name="JD 6120M",
        yard={"latitude": 9.05, "longitude": 7.45},
        field={"latitude": 9.07, "longitude": 7.47},
    )
    values.update(overrides)
    return TractorCreate(**values)


def test_valid_tractor():
    validate_tractor(tractor())


def test_tractor_tank_band():
    with pytest.raises(ValidationError):
        tractor(tank_capacity_l=1000)
    with pytest.raises(ValidationError):
        tractor(tank_capacity_l=100)


def test_field_too_far_from_yard():
    with pytest.raises(ProvisioningError, match="25 km"):
        validate_tractor(tractor(field={"latitude": 9.5, "longitude": 7.47}))


def test_working_hours_order():
    with pytest.raises(ValidationError):
        tractor(working_hours_start=18, working_hours_end=6)


# --- field geometry ---

FIELD = FieldGeometry(9.07, 7.47, width_m=400, length_m=600, heading_deg=30)


def test_field_round_trip():
    lat, lon = field_to_latlon(FIELD, 120.0, -80.0)
    along, across = latlon_to_field(FIELD, lat, lon)
    assert along == pytest.approx(120.0, abs=0.01)
    assert across == pytest.approx(-80.0, abs=0.01)


def test_polygon_closed_with_right_side_lengths():
    ring = field_polygon(FIELD)
    assert ring[0] == ring[-1] and len(ring) == 5
    assert haversine_m(*ring[0], *ring[1]) == pytest.approx(600, rel=0.01)
    assert haversine_m(*ring[1], *ring[2]) == pytest.approx(400, rel=0.01)


def test_contains():
    assert contains(FIELD, FIELD.latitude, FIELD.longitude)
    outside = field_to_latlon(FIELD, 0, 250)
    assert not contains(FIELD, *outside)
    assert contains(FIELD, *outside, margin_m=60)


def test_passes_cover_field():
    width = 4.0
    passes = boustrophedon_passes(FIELD, width, headland_m=12)
    covered = sum(p.length_m for p in passes) * width
    usable = (FIELD.width_m - 24) * (FIELD.length_m - 24)
    assert covered / usable >= 0.98
    # Alternating direction.
    assert passes[0].end_along_m > passes[0].start_along_m
    assert passes[1].end_along_m < passes[1].start_along_m


# --- rate limiter ---


def test_rate_limiter_window():
    clock = [0.0]
    limiter = SlidingWindowLimiter(2, 60.0, clock=lambda: clock[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")
    clock[0] = 61.0
    assert limiter.allow("a")
