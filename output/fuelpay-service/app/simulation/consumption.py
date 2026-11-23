"""Fuel consumption physics.

Pure functions, no I/O, no randomness — directly unit-testable.

All constants are sourced in resources/genset-fuel-consumption-reference.md.
Core relation:

    L/hr = kVA x power_factor x load_fraction x SFC(load_fraction) x size_penalty(kVA)
"""

# Specific fuel consumption (litres per kWh) against load fraction.
# Diesels burn proportionally more fuel when lightly loaded, so this is a
# curve rather than a constant. Source: waltpower.com.
SFC_CURVE: tuple[tuple[float, float], ...] = (
    (0.25, 0.35),
    (0.50, 0.30),
    (0.75, 0.26),
    (1.00, 0.24),
)

# Industry-standard kVA -> kW conversion assumption.
DEFAULT_POWER_FACTOR = 0.8

# The published SFC curve is generic, but small engines really are less
# efficient than large ones. Without a correction the formula tracks 100 kVA
# charts almost exactly while running ~20% light at 25 kVA. This factor is
# FITTED to close that gap, not sourced.
SIZE_PENALTY_AT_MIN_KVA = 0.25
SIZE_PENALTY_MIN_KVA = 25.0
SIZE_PENALTY_MAX_KVA = 100.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sfc_l_per_kwh(load_fraction: float) -> float:
    """Specific fuel consumption at a given load fraction (0.0-1.0).

    Linear interpolation across SFC_CURVE. Below 25% load the curve is held
    flat at 0.35 rather than extrapolated: extrapolation diverges quickly and
    light-load running is dominated by idle overhead the curve doesn't model.
    """
    if load_fraction <= SFC_CURVE[0][0]:
        return SFC_CURVE[0][1]
    if load_fraction >= SFC_CURVE[-1][0]:
        return SFC_CURVE[-1][1]

    for (x0, y0), (x1, y1) in zip(SFC_CURVE, SFC_CURVE[1:], strict=False):
        if x0 <= load_fraction <= x1:
            span = x1 - x0
            weight = (load_fraction - x0) / span
            return y0 + weight * (y1 - y0)

    return SFC_CURVE[-1][1]  # unreachable; satisfies the type checker


def size_penalty(kva_rating: float) -> float:
    """Small-engine inefficiency multiplier: 1.25 at 25 kVA -> 1.00 at 100 kVA.

    Clamped outside the 25-100 kVA band so out-of-range ratings degrade
    gracefully instead of producing absurd multipliers.
    """
    span = SIZE_PENALTY_MAX_KVA - SIZE_PENALTY_MIN_KVA
    position = _clamp((kva_rating - SIZE_PENALTY_MIN_KVA) / span, 0.0, 1.0)
    return 1.0 + SIZE_PENALTY_AT_MIN_KVA * (1.0 - position)


def load_kw(kva_rating: float, power_factor: float, load_fraction: float) -> float:
    """Real power drawn, in kW."""
    return kva_rating * power_factor * _clamp(load_fraction, 0.0, 1.0)


def fuel_rate_lph(kva_rating: float, power_factor: float, load_fraction: float) -> float:
    """Instantaneous burn rate in litres/hour.

    Returns 0.0 at zero load — a stopped engine burns nothing.
    """
    load_fraction = _clamp(load_fraction, 0.0, 1.0)
    if load_fraction <= 0.0:
        return 0.0

    kw = load_kw(kva_rating, power_factor, load_fraction)
    return kw * sfc_l_per_kwh(load_fraction) * size_penalty(kva_rating)


def max_burn_rate_lph(kva_rating: float, power_factor: float) -> float:
    """Burn rate at 100% load — the physical ceiling for this unit.

    The drain detector uses a multiple of this as its plausibility threshold.
    """
    return fuel_rate_lph(kva_rating, power_factor, 1.0)


def fuel_consumed_l(
    kva_rating: float,
    power_factor: float,
    load_fraction: float,
    minutes: float,
) -> float:
    """Litres burned over a period at a steady load."""
    return fuel_rate_lph(kva_rating, power_factor, load_fraction) * (minutes / 60.0)


def runtime_hours_remaining(
    fuel_level_l: float,
    kva_rating: float,
    power_factor: float,
    load_fraction: float,
) -> float | None:
    """Hours until dry at the current load. None if not burning."""
    rate = fuel_rate_lph(kva_rating, power_factor, load_fraction)
    if rate <= 0.0:
        return None
    return max(0.0, fuel_level_l) / rate
