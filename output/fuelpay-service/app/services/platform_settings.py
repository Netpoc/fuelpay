"""Runtime overrides set from the admin console.

Incident tuning starts from the environment (`Settings.theft_tuning`) and the
dataclass defaults (`VehicleTuning`), and an owner can override individual
fields from the dashboard without a restart. Overrides are stored as one JSON
document and merged at the start of every simulator run, so a change takes
effect on the next tick.

`merge_tuning` and `validate_tuning` are pure so the rules can be tested
without a database.
"""

from dataclasses import asdict, fields, replace
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.entities import PlatformSetting
from app.tuning import DEFAULT_VEHICLE, TheftTuning, VehicleTuning

TUNING_KEY = "tuning"
GROUPS = ("theft", "vehicle")


def _bounds(name: str) -> tuple[float, float]:
    if "hour" in name:
        return 0, 23
    if "probability" in name or "fraction" in name:
        return 0, 1
    if "factor" in name or "tolerance" in name:
        return 1, 3
    # Litres and pump rates.
    return 0, 10_000


def validate_tuning(overrides: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Drop nothing silently: unknown groups or fields, out-of-range values and
    inverted min/max pairs all raise ValueError with a readable message."""
    templates = {"theft": TheftTuning(), "vehicle": DEFAULT_VEHICLE}
    clean: dict[str, dict[str, float]] = {}
    for group, values in overrides.items():
        if group not in templates:
            raise ValueError(f"Unknown tuning group {group!r}.")
        if not isinstance(values, dict):
            raise ValueError(f"{group} must be an object.")
        known = {f.name: f.type for f in fields(templates[group])}
        out: dict[str, float] = {}
        for name, value in values.items():
            if name not in known:
                raise ValueError(f"Unknown setting {group}.{name}.")
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise ValueError(f"{group}.{name} must be a number.")
            low, high = _bounds(name)
            if not low <= value <= high:
                raise ValueError(f"{group}.{name} must be between {low} and {high}.")
            out[name] = int(value) if "hour" in name else float(value)
        merged = asdict(replace(templates[group], **out))
        for key in merged:
            if (
                key.endswith("_min_fraction")
                or key.endswith("_min_l")
                or key.endswith("_min_factor")
            ):
                partner = key.replace("_min_", "_max_")
                if partner in merged and merged[key] > merged[partner]:
                    raise ValueError(f"{group}.{key} cannot exceed {group}.{partner}.")
        if out:
            clean[group] = out
    return clean


def merge_tuning(
    base_theft: TheftTuning, overrides: dict[str, Any]
) -> tuple[TheftTuning, VehicleTuning]:
    """Apply stored overrides. Fields no longer present on the dataclass (a
    setting removed in a later release) are ignored rather than crashing a tick."""
    theft_fields = {f.name for f in fields(TheftTuning)}
    vehicle_fields = {f.name for f in fields(VehicleTuning)}
    theft = {k: v for k, v in (overrides.get("theft") or {}).items() if k in theft_fields}
    vehicle = {k: v for k, v in (overrides.get("vehicle") or {}).items() if k in vehicle_fields}
    return replace(base_theft, **theft), replace(DEFAULT_VEHICLE, **vehicle)


async def load_overrides(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(PlatformSetting, TUNING_KEY)
    return dict(row.value) if row else {}


async def load_tuning(
    session: AsyncSession, settings: Settings
) -> tuple[TheftTuning, VehicleTuning]:
    return merge_tuning(settings.theft_tuning, await load_overrides(session))


async def save_overrides(session: AsyncSession, overrides: dict, updated_by: str) -> None:
    statement = pg_insert(PlatformSetting).values(
        key=TUNING_KEY, value=overrides, updated_by=updated_by
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["key"], set_={"value": overrides, "updated_by": updated_by}
        )
    )


def effective_tuning(base_theft: TheftTuning, overrides: dict) -> dict[str, dict]:
    theft, vehicle = merge_tuning(base_theft, overrides)
    return {"theft": asdict(theft), "vehicle": asdict(vehicle)}


__all__ = [
    "GROUPS",
    "effective_tuning",
    "load_overrides",
    "load_tuning",
    "merge_tuning",
    "save_overrides",
    "validate_tuning",
]
