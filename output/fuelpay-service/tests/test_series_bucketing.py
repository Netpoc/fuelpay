"""Bucket selection for the charting endpoint.

Pure, so it tests without a database — the SQL that consumes the chosen bucket
is exercised against a live instance separately.
"""

from app.api.telemetry import BUCKET_LADDER, DEFAULT_TARGET_POINTS, choose_bucket_minutes


def points_for(hours: float, bucket: int) -> float:
    return (hours * 60) / bucket


def test_every_supported_window_stays_under_the_point_budget():
    """The reason this endpoint exists: 60 days of 5-minute readings is 17,280
    points, over the raw endpoint's 5,000-row cap and unusable in a chart."""
    for hours in (1, 6, 24, 24 * 7, 24 * 30, 24 * 60, 24 * 365):
        bucket = choose_bucket_minutes(hours)
        assert points_for(hours, bucket) <= DEFAULT_TARGET_POINTS, hours


def test_short_windows_keep_native_resolution():
    # A day at 5-minute native resolution is 288 points — no need to smooth it.
    assert choose_bucket_minutes(24) <= 5


def test_a_month_is_coarsened_but_still_detailed():
    bucket = choose_bucket_minutes(24 * 30)
    assert bucket in BUCKET_LADDER
    # Roughly hourly: fine enough that a refill is still a visible step.
    assert 60 <= bucket <= 180


def test_bucket_grows_monotonically_with_the_window():
    """A longer window must never come back at a finer bucket."""
    previous = 0
    for hours in (1, 6, 12, 24, 72, 24 * 7, 24 * 30, 24 * 90, 24 * 365):
        bucket = choose_bucket_minutes(hours)
        assert bucket >= previous, hours
        previous = bucket


def test_always_returns_a_ladder_value():
    for hours in (0.25, 1, 3.7, 100, 5000, 9000):
        assert choose_bucket_minutes(hours) in BUCKET_LADDER


def test_degenerate_windows_do_not_divide_by_zero():
    assert choose_bucket_minutes(0) == BUCKET_LADDER[0]
    assert choose_bucket_minutes(-5) == BUCKET_LADDER[0]


def test_absurd_window_clamps_to_the_coarsest_bucket():
    assert choose_bucket_minutes(24 * 10_000) == BUCKET_LADDER[-1]
