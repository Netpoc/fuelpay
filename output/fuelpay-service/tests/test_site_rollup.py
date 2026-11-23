"""Per-site tier rollup — the arithmetic behind a map pin.

The rule under test is the one the whole product rests on: a level is only ever
measured. Summing a tier over the tanks that happen to be reporting, and saying
how many that was, is the difference between "this site is half empty" and "we
can only see half of this site". A pin is one glyph and cannot afford to
conflate them.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.api.tanks import _tier_rollup
from app.models.entities import SensorStatus, TankKind
from app.schemas import TankState

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def tank(
    capacity_l: float,
    level_l: float | None,
    *,
    threshold: float = 25.0,
    kind: TankKind = TankKind.BULK,
    measured_at: datetime | None = NOW,
) -> TankState:
    """A tank state with only the fields the rollup reads varying."""
    reporting = level_l is not None
    return TankState(
        id=uuid.uuid4(),
        site_id=uuid.uuid4(),
        generator_id=None,
        name="Bulk 1",
        kind=kind,
        capacity_l=capacity_l,
        reorder_threshold_pct=threshold,
        sensor_model="ACME-1",
        sensor_serial="SN-1",
        calibrated_at=NOW,
        last_seen_at=measured_at if reporting else None,
        sensor_status=SensorStatus.ONLINE if reporting else SensorStatus.OFFLINE,
        level_l=level_l,
        level_pct=(level_l / capacity_l * 100.0) if reporting and capacity_l else None,
        measured_at=measured_at if reporting else None,
        stale_seconds=0.0 if reporting else None,
    )


class TestTierRollup:
    def test_sums_levels_and_capacity(self):
        tier = _tier_rollup([tank(5000, 4000), tank(5000, 1000)])

        assert tier.capacity_l == 10_000.0
        assert tier.level_l == 5000.0
        assert tier.level_pct == 50.0
        assert (tier.reporting, tier.total) == (2, 2)

    def test_capacity_counts_dark_tanks_but_level_does_not(self):
        """The headline number a partial site must not be allowed to tell.

        Capacity is a property of the steel and is always known. The level is
        summed over what reported. Dividing one by the other understates a site
        whose sensor is dark — which is why `reporting` rides along, so a caller
        can see the total was taken over a subset.
        """
        tier = _tier_rollup([tank(5000, 4000), tank(5000, None)])

        assert tier.capacity_l == 10_000.0
        assert tier.level_l == 4000.0
        # 40% of the site's steel, but 80% of the half we can actually see.
        assert tier.level_pct == 40.0
        assert (tier.reporting, tier.total) == (1, 2)

    def test_no_tank_reporting_yields_null_level_not_zero(self):
        """Zero would assert the site is empty. Null says nobody looked."""
        tier = _tier_rollup([tank(5000, None), tank(5000, None)])

        assert tier.level_l is None
        assert tier.level_pct is None
        assert tier.capacity_l == 10_000.0
        assert (tier.reporting, tier.total) == (0, 2)

    def test_empty_tier(self):
        """A site with no bulk tank at all still has to produce a row."""
        tier = _tier_rollup([])

        assert tier.capacity_l == 0.0
        assert tier.level_l is None
        assert tier.level_pct is None
        assert (tier.reporting, tier.total) == (0, 0)
        assert tier.threshold == 0.0

    def test_zero_capacity_does_not_divide(self):
        tier = _tier_rollup([tank(0.0, 0.0)])

        assert tier.level_pct is None

    def test_threshold_is_the_strictest_in_the_tier(self):
        """Tanks on one site can disagree; the safe read is the highest line."""
        tier = _tier_rollup([tank(5000, 4000, threshold=20.0), tank(5000, 4000, threshold=30.0)])

        assert tier.threshold == 30.0

    def test_levels_are_rounded_to_two_places(self):
        tier = _tier_rollup([tank(5000, 1234.567), tank(5000, 1000.001)])

        assert tier.level_l == 2234.57


class TestReportingIsIndependentOfSignal:
    """`reporting` and a dark sensor are different questions.

    `level_l` is the last level a tank measured, however old — the query behind
    it has no time bound. `sensor_status` is whether it has said anything
    recently. So a tank can be counted as reporting *and* be dark, and a caller
    that reads `reporting == total` as "these numbers are current" is wrong.
    This test pins that down so the endpoint's contract cannot quietly change.
    """

    def test_a_long_dead_sensor_still_counts_as_reporting(self):
        stale = tank(5000, 4000, measured_at=NOW - timedelta(days=3))
        stale.sensor_status = SensorStatus.OFFLINE

        tier = _tier_rollup([stale])

        assert tier.reporting == tier.total == 1
        assert tier.level_l == 4000.0
        # Nothing here reveals the sensor is dark — that is `dark_sensors`'
        # job on SiteSummary, and it is why the two must be read together.
        assert stale.sensor_status is SensorStatus.OFFLINE
