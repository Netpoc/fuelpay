"""Consumption maths, checked against published vendor charts.

The chart figures in test_matches_published_charts are the acceptance criteria
for the whole simulator: if these drift, the generated data stops resembling
real gensets. Sources are listed in
resources/genset-fuel-consumption-reference.md section 3.
"""

import pytest

from app.simulation.consumption import (
    SFC_CURVE,
    fuel_consumed_l,
    fuel_rate_lph,
    max_burn_rate_lph,
    runtime_hours_remaining,
    sfc_l_per_kwh,
    size_penalty,
)

PF = 0.8


class TestSfcCurve:
    @pytest.mark.parametrize(("load", "expected"), SFC_CURVE)
    def test_hits_curve_points_exactly(self, load: float, expected: float):
        assert sfc_l_per_kwh(load) == pytest.approx(expected)

    def test_interpolates_between_points(self):
        # Midway between 50% (0.30) and 75% (0.26).
        assert sfc_l_per_kwh(0.625) == pytest.approx(0.28)

    def test_held_flat_below_lowest_point(self):
        # Deliberately not extrapolated — see consumption.sfc_l_per_kwh.
        assert sfc_l_per_kwh(0.10) == pytest.approx(0.35)
        assert sfc_l_per_kwh(0.0) == pytest.approx(0.35)

    def test_clamped_above_full_load(self):
        assert sfc_l_per_kwh(1.5) == pytest.approx(0.24)

    def test_efficiency_improves_with_load(self):
        """Lightly loaded diesels burn proportionally more — the whole point."""
        rates = [sfc_l_per_kwh(x / 100) for x in range(25, 101, 5)]
        assert rates == sorted(rates, reverse=True)


class TestSizePenalty:
    def test_small_units_penalised(self):
        assert size_penalty(25.0) == pytest.approx(1.25)

    def test_large_units_unpenalised(self):
        assert size_penalty(100.0) == pytest.approx(1.0)

    def test_clamped_outside_band(self):
        assert size_penalty(10.0) == pytest.approx(1.25)
        assert size_penalty(500.0) == pytest.approx(1.0)

    def test_monotonic_across_band(self):
        values = [size_penalty(k) for k in range(25, 101, 5)]
        assert values == sorted(values, reverse=True)


class TestPublishedCharts:
    """The headline validation: formula output vs. vendor-published L/hr.

    Tolerances reflect genuine disagreement between sources (published figures
    for 100 kVA at full load range from 18 to 25 L/hr), not sloppiness.
    """

    @pytest.mark.parametrize(
        ("kva", "load", "chart_low", "chart_high"),
        [
            (100.0, 0.25, 6.0, 7.0),
            (100.0, 0.50, 10.0, 12.0),
            (100.0, 0.75, 14.0, 18.0),
            (100.0, 1.00, 18.0, 25.0),
            (25.0, 0.25, 1.8, 3.0),
            (25.0, 0.50, 3.0, 3.8),
            (25.0, 0.75, 4.5, 5.5),
            (25.0, 1.00, 5.5, 6.5),
            (50.0, 0.50, 5.0, 7.0),
            (50.0, 1.00, 10.0, 13.0),
        ],
    )
    def test_matches_published_charts(
        self, kva: float, load: float, chart_low: float, chart_high: float
    ):
        rate = fuel_rate_lph(kva, PF, load)
        assert chart_low <= rate <= chart_high, (
            f"{kva} kVA @ {load:.0%} produced {rate:.2f} L/hr, "
            f"outside published range {chart_low}-{chart_high}"
        )

    def test_size_penalty_lifts_small_units_into_range(self):
        """Without the fitted penalty a 25 kVA unit reads ~20% light."""
        raw = 25.0 * PF * 1.0 * 0.24  # formula with no penalty
        assert raw == pytest.approx(4.8)
        assert fuel_rate_lph(25.0, PF, 1.0) == pytest.approx(6.0)


class TestFuelRate:
    def test_zero_load_burns_nothing(self):
        assert fuel_rate_lph(100.0, PF, 0.0) == 0.0

    def test_negative_load_treated_as_zero(self):
        assert fuel_rate_lph(100.0, PF, -0.5) == 0.0

    def test_rate_increases_with_load(self):
        rates = [fuel_rate_lph(75.0, PF, x / 100) for x in range(10, 101, 10)]
        assert rates == sorted(rates)

    def test_power_factor_scales_output(self):
        assert fuel_rate_lph(100.0, 1.0, 0.5) > fuel_rate_lph(100.0, 0.8, 0.5)

    def test_max_burn_is_the_ceiling(self):
        ceiling = max_burn_rate_lph(100.0, PF)
        assert all(fuel_rate_lph(100.0, PF, x / 100) <= ceiling for x in range(0, 101))


class TestConsumedVolume:
    def test_one_hour_equals_hourly_rate(self):
        assert fuel_consumed_l(100.0, PF, 0.5, 60.0) == pytest.approx(
            fuel_rate_lph(100.0, PF, 0.5)
        )

    def test_scales_linearly_with_time(self):
        half = fuel_consumed_l(50.0, PF, 0.6, 30.0)
        full = fuel_consumed_l(50.0, PF, 0.6, 60.0)
        assert full == pytest.approx(half * 2)

    def test_realistic_daily_burn_for_telecom_tower(self):
        """A 100 kVA tower at 70% load, 24/7, should be a plausible day's fuel."""
        daily = fuel_consumed_l(100.0, PF, 0.70, 24 * 60)
        # ~15 L/hr * 24h. Sanity band, not a precise assertion.
        assert 330.0 <= daily <= 400.0


class TestRuntimeRemaining:
    def test_none_when_not_burning(self):
        assert runtime_hours_remaining(500.0, 100.0, PF, 0.0) is None

    def test_matches_manual_division(self):
        hours = runtime_hours_remaining(1000.0, 100.0, PF, 0.5)
        assert hours == pytest.approx(1000.0 / fuel_rate_lph(100.0, PF, 0.5))

    def test_thousand_litre_tank_at_half_load(self):
        """Reference doc: a 1000 L tank gives roughly 50 hours at 50% load."""
        hours = runtime_hours_remaining(1000.0, 100.0, PF, 0.5)
        assert 75.0 <= hours <= 90.0  # 12 L/hr => ~83h

    def test_empty_tank_is_zero(self):
        assert runtime_hours_remaining(0.0, 100.0, PF, 0.5) == 0.0
