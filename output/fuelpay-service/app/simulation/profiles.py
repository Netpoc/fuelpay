"""Load profiles — what the generator is actually being asked to power.

Load drives everything downstream: consumption is a function of it, and the
SFC curve makes that relationship non-linear. Getting these shapes right
matters more than any other simulation input.

A load fraction of 0.0 means the engine is off (burning nothing).
Profiles are centred so their peak sits in the 50-75% band where diesels run
most efficiently. See resources/genset-fuel-consumption-reference.md section 5.
"""

from datetime import datetime

from app.models.entities import SiteProfile

# Target load fraction for each hour of the day, index 0 = 00:00.
# Values are interpolated across the hour boundary, wrapping at midnight.
HOURLY_LOAD: dict[SiteProfile, tuple[float, ...]] = {
    # Always-on base load. Runs 24/7, dips slightly overnight when ambient
    # cooling demand falls. The classic unmanned-site profile.
    SiteProfile.TELECOM_TOWER: (
        0.66, 0.65, 0.65, 0.65, 0.66, 0.68,  # 00-05
        0.70, 0.72, 0.73, 0.74, 0.75, 0.75,  # 06-11
        0.75, 0.75, 0.74, 0.74, 0.73, 0.72,  # 12-17
        0.71, 0.70, 0.69, 0.68, 0.67, 0.66,  # 18-23
    ),
    # Building base load overnight (servers, security, lifts), ramping hard
    # across business hours. Never fully off — see WEEKEND_SCALE below.
    SiteProfile.OFFICE: (
        0.20, 0.20, 0.20, 0.20, 0.20, 0.22,  # 00-05
        0.30, 0.50, 0.70, 0.78, 0.80, 0.80,  # 06-11
        0.76, 0.78, 0.80, 0.79, 0.75, 0.60,  # 12-17
        0.40, 0.28, 0.22, 0.20, 0.20, 0.20,  # 18-23
    ),
    # Estate genset covering grid outages: a morning burst, off through the
    # working day, then a sharp evening peak for lighting and cooling.
    SiteProfile.RESIDENTIAL: (
        0.00, 0.00, 0.00, 0.00, 0.00, 0.25,  # 00-05
        0.40, 0.45, 0.35, 0.00, 0.00, 0.00,  # 06-11
        0.00, 0.00, 0.00, 0.00, 0.00, 0.55,  # 12-17
        0.75, 0.80, 0.78, 0.70, 0.55, 0.30,  # 18-23
    ),
    # Nigerian bank branch. Unlike an office this never drops to a bare base
    # load: ATMs, the vault, CCTV and the comms link run through the night, so
    # the floor sits around 30% rather than 20%. The banking-hours peak is
    # driven as much by air conditioning as by the hall itself, and the branch
    # keeps drawing after close while staff finish the day's reconciliation.
    SiteProfile.BANK_BRANCH: (
        0.30, 0.29, 0.29, 0.29, 0.30, 0.32,  # 00-05
        0.38, 0.52, 0.70, 0.82, 0.86, 0.87,  # 06-11
        0.85, 0.86, 0.87, 0.85, 0.78, 0.62,  # 12-17
        0.48, 0.40, 0.36, 0.34, 0.32, 0.31,  # 18-23
    ),
}

# Weekend demand multiplier. Telecom load is indifferent to the calendar;
# offices empty out; homes are occupied more of the day.
WEEKEND_SCALE: dict[SiteProfile, float] = {
    SiteProfile.TELECOM_TOWER: 1.00,
    SiteProfile.OFFICE: 0.30,
    SiteProfile.RESIDENTIAL: 1.15,
    # Branches shut on Sunday and run a short Saturday; the 24/7 ATM and
    # security load is what remains, not a full trading day.
    SiteProfile.BANK_BRANCH: 0.45,
}

# Default in-built (day) tank sizing per profile, in litres.
#
# The floor is 1000 L across every profile. Smaller tanks exist in the field
# but are not FuelPay's market, and the regulatory minimums in reference doc
# section 4 (100-225 L) describe a tank that needs refilling daily — nothing
# anyone would instrument. Larger units get a nudge up in `fleet.py` so a
# 100 kVA set doesn't need topping up twice as often as a 40 kVA one.
DEFAULT_TANK_CAPACITY_L: dict[SiteProfile, float] = {
    SiteProfile.TELECOM_TOWER: 1000.0,
    SiteProfile.OFFICE: 1000.0,
    SiteProfile.RESIDENTIAL: 1000.0,
    SiteProfile.BANK_BRANCH: 1500.0,
}

# Site bulk storage, in litres. 5000 L is the low end of what a Nigerian bank
# branch actually installs; a site's total is split across one or more tanks in
# `fleet.py`, since larger sites run several rather than one huge vessel.
DEFAULT_BULK_CAPACITY_L: dict[SiteProfile, float] = {
    SiteProfile.TELECOM_TOWER: 5000.0,
    SiteProfile.OFFICE: 5000.0,
    SiteProfile.RESIDENTIAL: 5000.0,
    SiteProfile.BANK_BRANCH: 10000.0,
}

# Below this fraction the engine is treated as off rather than idling.
ENGINE_OFF_THRESHOLD = 0.02


def _interpolate_hourly(table: tuple[float, ...], moment: datetime) -> float:
    """Read the hourly table at a fractional hour, wrapping across midnight.

    Interpolating avoids step changes at hour boundaries, which would show up
    as implausible sawtooth edges in the telemetry.
    """
    position = moment.hour + moment.minute / 60.0 + moment.second / 3600.0
    low_index = int(position) % 24
    high_index = (low_index + 1) % 24
    weight = position - int(position)

    # An off hour adjacent to an on hour must not be smoothed into a phantom
    # idle; treat the transition as a step so start/stop stays crisp.
    low, high = table[low_index], table[high_index]
    if low == 0.0 or high == 0.0:
        return low

    return low + weight * (high - low)


def target_load_fraction(profile: SiteProfile, moment: datetime) -> float:
    """Baseline load fraction for this profile at this instant, before noise.

    Returns 0.0 when the engine should be off.
    """
    table = HOURLY_LOAD[profile]
    base = _interpolate_hourly(table, moment)
    if base <= 0.0:
        return 0.0

    is_weekend = moment.weekday() >= 5
    if is_weekend:
        base *= WEEKEND_SCALE[profile]

    return max(0.0, min(1.0, base))


def is_engine_running(load_fraction: float) -> bool:
    return load_fraction > ENGINE_OFF_THRESHOLD


def default_tank_capacity_l(profile: SiteProfile) -> float:
    return DEFAULT_TANK_CAPACITY_L[profile]


def default_bulk_capacity_l(profile: SiteProfile) -> float:
    return DEFAULT_BULK_CAPACITY_L[profile]
