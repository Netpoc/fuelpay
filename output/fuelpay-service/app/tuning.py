"""Tunable simulation rates.

These were constants inside `engine.step`. They became parameters so a demo can
make siphons frequent enough to watch without editing code, and so the values
live in one place that both `Settings` and the pure engine can see.

This module deliberately imports nothing from the rest of the app, and sits
above `app.simulation` rather than inside it. `app.config` needs these types,
and importing anything from the simulation package runs its `__init__`, which
pulls in the engine -> `app.models.entities` -> `app.db` -> back to
`app.config`. `app/__init__.py` is empty, so importing `app.tuning` triggers
nothing.

The defaults reproduce the previous hard-coded behaviour exactly, so a caller
that passes nothing gets the simulation it got before.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TheftTuning:
    """How often fuel is siphoned, how much goes, and when thieves work.

    The hour window matters as much as the probability: raising the odds while
    leaving the window at 22:00–04:00 still yields no theft during a midday
    demo, which reads as the setting being broken.
    """

    probability_per_day: float = 0.015
    volume_min_fraction: float = 0.20
    volume_max_fraction: float = 0.40
    window_start_hour: int = 22
    window_end_hour: int = 4


@dataclass(frozen=True)
class RefillWindow:
    """The hours a tanker will deliver in.

    Outside it, only a tank below the emergency threshold gets filled — which
    is what makes a 03:00 refill in the data worth a second look.
    """

    start_hour: int = 8
    end_hour: int = 17


@dataclass(frozen=True)
class DeliveryTuning:
    """Tanker deliveries into bulk storage, and how honest they are.

    Short delivery is the fraud the bulk-tank sensor exists to catch: the site
    is billed for a full load, the truck drops less, and without a sensor on
    the receiving tank nobody can prove the difference. `tolerance_fraction`
    is the measurement slop below which a shortfall is not worth alleging.
    """

    short_probability: float = 0.12
    short_min_fraction: float = 0.04
    short_max_fraction: float = 0.18
    tolerance_fraction: float = 0.02


@dataclass(frozen=True)
class TransferTuning:
    """Bulk -> day tank replenishment.

    Transfers are pump-driven and quick, so unlike a tanker delivery they are
    not confined to an hour window: the day tank is topped up whenever it
    falls below its reorder threshold and the bulk tank has fuel to give.
    """

    target_min_fraction: float = 0.92
    target_max_fraction: float = 1.00
    # Litres a transfer pump moves per minute. Caps how much a single tick can
    # shift, so a large day tank refills over several ticks rather than
    # teleporting to full.
    pump_rate_lpm: float = 40.0


@dataclass(frozen=True)
class SensorTuning:
    """How often a fuel sensor drops off the network, and for how long.

    Signal loss matters beyond data completeness. A gap is precisely when a
    level discontinuity stops being attributable, so these rates decide how
    often the fleet produces that ambiguity.
    """

    dropout_probability_per_day: float = 0.04
    min_out_ticks: int = 2
    max_out_ticks: int = 24
    # A level drop across a gap larger than this fraction of capacity is
    # reported as an unverified loss rather than written off as consumption.
    unverified_loss_threshold_fraction: float = 0.05


@dataclass(frozen=True)
class VehicleTuning:
    """Incident rates for mobile machinery (tractors).

    Probabilities are per working day unless noted. They are set so a 30-day
    demo history shows each kind of incident at least once on a typical
    machine without making the fleet look lawless.
    """

    # Siphoning from the tank overnight in the yard.
    siphon_probability_per_day: float = 0.04
    siphon_min_l: float = 40.0
    siphon_max_l: float = 120.0
    siphon_rate_lpm: float = 15.0
    # Fuel diverted from the injection return line: the level falls faster than
    # the engine's own consumption figure says it should.
    return_line_probability: float = 0.06
    return_line_min_factor: float = 1.25
    return_line_max_factor: float = 1.40
    # Per refuel: billed for more than reached the tank.
    short_fill_probability: float = 0.12
    short_fill_min_fraction: float = 0.08
    short_fill_max_fraction: float = 0.15
    # Use outside the job.
    after_hours_probability: float = 0.05
    off_field_probability: float = 0.05
    # Days the operator or soil simply burns more than the norm.
    heavy_day_probability: float = 0.06
    # Ratio of actual to quota litres-per-hectare above which a day is flagged.
    quota_tolerance: float = 1.15


DEFAULT_THEFT = TheftTuning()
DEFAULT_REFILL_WINDOW = RefillWindow()
DEFAULT_DELIVERY = DeliveryTuning()
DEFAULT_TRANSFER = TransferTuning()
DEFAULT_SENSOR = SensorTuning()
DEFAULT_VEHICLE = VehicleTuning()
