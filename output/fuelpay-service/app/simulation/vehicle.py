"""Tractor simulation: a working day of agricultural telematics.

Pure and deterministic, like the site stepper. Randomness comes from
`rng_for(seed, vehicle_id, ...)`, so a machine's history depends only on its
own id and the seed, never on what else is in the fleet.

The machine steps one simulated minute at a time. Field work at 7 km/h covers
~120 m a minute, so anything coarser would draw passes as a zigzag of chords
instead of the back-and-forth pattern a real track shows. A reading is emitted
every minute while the engine runs and every five while it is off, which is
about what a telematics unit on a power-saving schedule does.

The day, in local time:

    OFF (yard) -> [REFUEL] -> WARMUP -> TRANSIT -> WORK -> LUNCH -> WORK
               -> TRANSIT -> [REFUEL] -> OFF

with three kinds of incident layered on top:

- theft from the tank: an overnight siphon in the yard (SUSPECTED_DRAIN), a
  return-line diversion that makes the level fall faster than the engine's
  own consumption figure (OVERCONSUMPTION, kind=return_line), and a refuel
  billed for more than reached the tank (SHORT_FILL);
- misuse: an evening trip after hours, or a detour off the field mid-shift
  (MISUSE);
- plain inefficiency: a day whose litres per hectare exceed the operation's
  quota (OVERCONSUMPTION, kind=quota).

As with site tanks, `fuel_level_l` in state is the truth and a reading carries
sensor noise on top. `consumed_l` on a reading is what the engine's CAN bus
reports — the number a return-line thief leaves untouched — so the gap between
it and the level is what makes that theft visible.
"""

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache

from app.models.entities import EventType, VehicleOperation
from app.simulation.engine import EventSample, rng_for
from app.simulation.field import (
    FieldGeometry,
    Pass,
    bearing_deg,
    boustrophedon_passes,
    contains,
    field_to_latlon,
    local_offset,
    offset_latlon,
)
from app.tuning import DEFAULT_VEHICLE, VehicleTuning

STEP = timedelta(minutes=1)
OFF_READING_EVERY_MINUTES = 5

DIESEL_KG_PER_L = 0.835
# Brake-specific fuel consumption (kg/kWh) against load. Agricultural diesels
# sit a little above genset curves at part load. Interpolated linearly.
BSFC_CURVE: tuple[tuple[float, float], ...] = (
    (0.10, 0.42),
    (0.25, 0.30),
    (0.50, 0.26),
    (0.75, 0.24),
    (1.00, 0.235),
)

# Per operation: engine load, working speed (km/h), implement width (m) for a
# 90 kW reference tractor, and the per-hectare fuel quota (L/ha). Widths scale
# with engine power, which keeps litres per hectare roughly size-independent.
REFERENCE_KW = 90.0


@dataclass(frozen=True)
class OperationProfile:
    load: float
    speed_kmh: float
    width_m: float
    quota_l_per_ha: float | None


OPERATIONS: dict[VehicleOperation, OperationProfile] = {
    VehicleOperation.PLOUGHING: OperationProfile(0.82, 7.0, 1.8, 18.0),
    VehicleOperation.HARROWING: OperationProfile(0.60, 9.0, 4.0, 6.0),
    VehicleOperation.SOWING: OperationProfile(0.45, 8.0, 4.0, 5.0),
    VehicleOperation.SPRAYING: OperationProfile(0.35, 10.0, 18.0, 1.0),
    # Hauling a trailer back and forth across the field.
    VehicleOperation.TRANSPORT: OperationProfile(0.50, 12.0, 12.0, None),
}
FIELD_OPERATIONS = tuple(OPERATIONS)

IDLE_LOAD = 0.12
TRANSIT_LOAD = 0.35
HEADLAND_M = 12.0
FIELD_MARGIN_M = 15.0

REFUEL_RATE_LPM = 40.0
REFUEL_BELOW_FRACTION = 0.55
REFUEL_TARGET_MIN = 0.95
LOW_FUEL_FRACTION = 0.15
# Below this mid-shift the machine heads home to refuel, then goes back out.
RETURN_FRACTION = 0.20

SENSOR_NOISE_FRACTION = 0.008
SLOSH_NOISE_FRACTION = 0.008
LEVEL_QUANTISATION_L = 0.1
GPS_JITTER_M = 2.5

AMBIENT_C = 30.0


@dataclass(frozen=True)
class VehicleSpec:
    id: uuid.UUID
    organisation_id: uuid.UUID
    engine_kw: float
    tank_capacity_l: float
    yard_latitude: float
    yard_longitude: float
    field: FieldGeometry
    primary_operation: VehicleOperation
    working_hours_start: int = 6
    working_hours_end: int = 18
    utc_offset_hours: int = 1


@dataclass(frozen=True)
class VehicleState:
    """Resume cursor. `memory` is JSON-safe: it is persisted as JSONB."""

    simulated_at: datetime
    tick_index: int
    fuel_level_l: float
    engine_hours: float
    memory: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VehicleReadingSample:
    vehicle_id: uuid.UUID
    organisation_id: uuid.UUID
    time: datetime
    latitude: float
    longitude: float
    speed_kmh: float
    heading_deg: float
    engine_on: bool
    rpm: float
    fuel_level_l: float
    fuel_level_pct: float
    fuel_rate_lph: float
    coolant_c: float
    oil_kpa: float
    engine_hours: float
    operation: VehicleOperation
    consumed_l: float
    distance_m: float
    area_ha: float


# --- physics -----------------------------------------------------------------


def bsfc_kg_per_kwh(load: float) -> float:
    if load <= BSFC_CURVE[0][0]:
        return BSFC_CURVE[0][1]
    for (x0, y0), (x1, y1) in zip(BSFC_CURVE, BSFC_CURVE[1:], strict=False):
        if load <= x1:
            return y0 + (load - x0) / (x1 - x0) * (y1 - y0)
    return BSFC_CURVE[-1][1]


def fuel_rate_lph(engine_kw: float, load: float) -> float:
    """Litres per hour at a given engine load. Zero load is a stopped engine."""
    if load <= 0.0:
        return 0.0
    return engine_kw * load * bsfc_kg_per_kwh(load) / DIESEL_KG_PER_L


def implement_width_m(spec: VehicleSpec, operation: VehicleOperation) -> float:
    return OPERATIONS[operation].width_m * spec.engine_kw / REFERENCE_KW


@lru_cache(maxsize=256)
def _passes(field_geometry: FieldGeometry, width_m: float) -> tuple[Pass, ...]:
    return tuple(boustrophedon_passes(field_geometry, width_m, HEADLAND_M))


def passes_for(spec: VehicleSpec, operation: VehicleOperation) -> tuple[Pass, ...]:
    return _passes(spec.field, round(implement_width_m(spec, operation), 3))


def local_time(spec: VehicleSpec, moment: datetime) -> datetime:
    return moment + timedelta(hours=spec.utc_offset_hours)


# --- the day plan ------------------------------------------------------------


def make_day_plan(spec: VehicleSpec, local_day: datetime, seed: int, tuning: VehicleTuning) -> dict:
    """Everything decided about a day up front, from that day's own RNG."""
    day_number = local_day.toordinal()
    rng = rng_for(seed, spec.id, day_number, "plan")
    weekday = local_day.weekday()
    work_probability = 0.15 if weekday == 6 else 0.6 if weekday == 5 else 0.92

    start = spec.working_hours_start * 60
    end = spec.working_hours_end * 60
    plan: dict = {
        "work": rng.random() < work_probability,
        "operation": (
            spec.primary_operation.value
            if rng.random() < 0.7
            else rng.choice(FIELD_OPERATIONS).value
        ),
        "start_min": start + rng.randint(0, 45),
        "end_min": end - rng.randint(0, 60),
        "lunch_min": 12 * 60 + rng.randint(15, 45),
        "lunch_len": rng.randint(30, 50),
        "efficiency": rng.uniform(0.93, 1.07),
        "transit_kmh": rng.uniform(18.0, 25.0),
    }
    if rng.random() < tuning.heavy_day_probability:
        plan["efficiency"] = rng.uniform(1.2, 1.32)
    if rng.random() < tuning.return_line_probability:
        plan["return_line"] = rng.uniform(
            tuning.return_line_min_factor, tuning.return_line_max_factor
        )
    if rng.random() < tuning.siphon_probability_per_day:
        # 22:00-04:00, expressed as this day's minute: early hours or late night.
        plan["siphon_min"] = (22 * 60 + rng.randint(0, 359)) % (24 * 60)
        plan["siphon_l"] = rng.uniform(tuning.siphon_min_l, tuning.siphon_max_l)
    if plan["work"] and rng.random() < tuning.off_field_probability:
        plan["off_field_min"] = rng.randint(plan["start_min"] + 90, plan["lunch_min"] + 180)
        plan["off_field_bearing"] = rng.uniform(0, 360)
        plan["off_field_m"] = rng.uniform(2_000, 6_000)
        plan["off_field_stay"] = rng.randint(20, 40)
    if rng.random() < tuning.after_hours_probability:
        plan["after_hours_min"] = min(end + rng.randint(60, 180), 23 * 60)
        plan["after_hours_bearing"] = rng.uniform(0, 360)
        plan["after_hours_m"] = rng.uniform(3_000, 8_000)
        plan["after_hours_stay"] = rng.randint(20, 45)
    return plan


def _new_day(memory: dict, plan: dict, day_number: int) -> None:
    memory["day"] = day_number
    memory["plan"] = plan
    memory["done"] = []
    memory["stats"] = {"can_l": 0.0, "true_l": 0.0, "work_l": 0.0, "area_ha": 0.0}


# --- state -------------------------------------------------------------------


def initial_vehicle_state(spec: VehicleSpec, start: datetime, seed: int) -> VehicleState:
    """Parked in the yard, engine cold, tank part-full."""
    rng = rng_for(seed, spec.id, 0, "init")
    start = start.replace(second=0, microsecond=0)
    return VehicleState(
        simulated_at=start,
        tick_index=0,
        fuel_level_l=spec.tank_capacity_l * rng.uniform(0.5, 0.9),
        engine_hours=round(rng.uniform(800, 4_000), 1),
        memory={
            "phase": "OFF",
            "lat": spec.yard_latitude,
            "lon": spec.yard_longitude,
            "heading": 0.0,
            "coolant": AMBIENT_C,
            "engine_on": False,
            "pass_index": 0,
            "along": None,
            "in_field": False,
            "low_fuel": False,
        },
    )


# --- stepping ----------------------------------------------------------------


@dataclass
class _Minute:
    """Scratch for one simulated minute."""

    operation: VehicleOperation = VehicleOperation.OFF
    load: float = 0.0
    speed_kmh: float = 0.0
    distance_m: float = 0.0
    area_ha: float = 0.0
    refuelled_l: float = 0.0
    drained_l: float = 0.0
    # Litres burned as the engine reports it, and the rate behind it.
    can_l: float = 0.0
    norm_lph: float = 0.0
    events: list[EventSample] = field(default_factory=list)


class _Stepper:
    def __init__(self, spec: VehicleSpec, state: VehicleState, seed: int, tuning: VehicleTuning):
        self.spec = spec
        self.seed = seed
        self.tuning = tuning
        self.moment = state.simulated_at
        self.tick = state.tick_index
        self.fuel = state.fuel_level_l
        self.hours = state.engine_hours
        # Deep enough copy: nested dicts/lists are replaced, not mutated, below
        # except `done` and `stats`, which are copied here.
        # Day-end reconciliation events, drained by the span loop each minute.
        self.pending_close: list[EventSample] = []
        self.m = dict(state.memory)
        if "done" in self.m:
            self.m["done"] = list(self.m["done"])
        if "stats" in self.m:
            self.m["stats"] = dict(self.m["stats"])

    # -- helpers --

    def event(self, minute: _Minute, kind: EventType, volume: float | None, detail: dict) -> None:
        minute.events.append(
            EventSample(
                organisation_id=self.spec.organisation_id,
                vehicle_id=self.spec.id,
                event_type=kind,
                occurred_at=self.moment,
                volume_l=None if volume is None else round(volume, 2),
                fuel_level_l=round(self.fuel, 2),
                detail=detail,
            )
        )

    def done(self, key: str) -> bool:
        return key in self.m["done"]

    def mark(self, key: str) -> None:
        self.m["done"].append(key)

    def plan(self) -> dict:
        return self.m["plan"]

    def operation(self) -> VehicleOperation:
        return VehicleOperation(self.plan()["operation"])

    def go(self, target: tuple[float, float], then: str, kmh: float, op: str = "TRANSIT") -> None:
        self.m["phase"] = "TRANSIT"
        self.m["target"] = [target[0], target[1]]
        self.m["then"] = then
        self.m["kmh"] = kmh
        self.m["leg_op"] = op

    def field_entry(self) -> tuple[float, float]:
        passes = passes_for(self.spec, self.operation())
        index = self.m["pass_index"] % len(passes)
        current = passes[index]
        along = self.m["along"] if self.m["along"] is not None else current.start_along_m
        return field_to_latlon(self.spec.field, along, current.across_m)

    def yard(self) -> tuple[float, float]:
        return self.spec.yard_latitude, self.spec.yard_longitude

    # -- one minute --

    def step(self, rng: random.Random) -> _Minute:
        local = local_time(self.spec, self.moment)
        day_number = local.toordinal()
        if self.m.get("day") != day_number:
            if "plan" in self.m:
                self._close_day()
            plan = make_day_plan(self.spec, local.replace(hour=0, minute=0), self.seed, self.tuning)
            _new_day(self.m, plan, day_number)
        minute_of_day = local.hour * 60 + local.minute
        plan = self.plan()
        minute = _Minute()
        phase = self.m["phase"]

        if phase == "OFF":
            self._off(minute, minute_of_day, plan)
        elif phase == "REFUEL":
            self._refuel(minute, rng)
        elif phase == "WARMUP":
            minute.operation, minute.load = VehicleOperation.IDLE, IDLE_LOAD
            self.m["warm"] = self.m.get("warm", 0) - 1
            if self.m["warm"] <= 0:
                if self.m.get("after_hours_trip"):
                    target = offset_latlon(
                        *self.yard(),
                        plan["after_hours_m"] * math.sin(math.radians(plan["after_hours_bearing"])),
                        plan["after_hours_m"] * math.cos(math.radians(plan["after_hours_bearing"])),
                    )
                    self.go(target, "AH_STOP", plan["transit_kmh"], "TRANSPORT")
                else:
                    self.go(self.field_entry(), "WORK", plan["transit_kmh"])
        elif phase == "TRANSIT":
            self._transit(minute)
        elif phase == "WORK":
            self._work(minute, minute_of_day, plan)
        elif phase == "LUNCH":
            if minute_of_day >= plan["lunch_min"] + plan["lunch_len"]:
                self.m["phase"] = "WORK"
                self._work(minute, minute_of_day, plan)
        elif phase in ("DETOUR_STOP", "AH_STOP"):
            minute.operation, minute.load = VehicleOperation.IDLE, IDLE_LOAD
            self.m["stay"] = self.m.get("stay", 0) - 1
            if self.m["stay"] <= 0:
                if phase == "DETOUR_STOP":
                    self.go(self.field_entry(), "WORK", plan["transit_kmh"])
                else:
                    self.go(self.yard(), "HOME", plan["transit_kmh"], "TRANSPORT")

        self._burn(minute)
        self._field_crossing(minute)
        return minute

    def _off(self, minute: _Minute, minute_of_day: int, plan: dict) -> None:
        if (
            "siphon_min" in plan
            and not self.done("siphon")
            and minute_of_day >= plan["siphon_min"]
            # Late-night siphons belong to the evening; an early-hours one
            # must not fire at 23:00 the same calendar day.
            and (plan["siphon_min"] >= 22 * 60 or minute_of_day < 4 * 60)
        ):
            self._siphon(minute, plan)
            return

        # Also restarts a shift interrupted by a trip home to refuel; only the
        # end of the working day closes it for good.
        if (
            plan["work"]
            and not self.done("shift_over")
            and plan["start_min"] <= minute_of_day < plan["end_min"] - 60
        ):
            self.m["after_hours_trip"] = False
            if self.fuel < self.spec.tank_capacity_l * REFUEL_BELOW_FRACTION:
                self.m["phase"], self.m["after_refuel"] = "REFUEL", "WARMUP"
            else:
                self.m["phase"], self.m["warm"] = "WARMUP", 6
            return

        if (
            "after_hours_min" in plan
            and not self.done("after_hours")
            and minute_of_day >= plan["after_hours_min"]
        ):
            self.mark("after_hours")
            self.m["after_hours_trip"] = True
            self.m["phase"], self.m["warm"] = "WARMUP", 3
            self.event(
                minute,
                EventType.MISUSE,
                None,
                {
                    "kind": "after_hours",
                    "local_time": f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}",
                },
            )

    def _siphon(self, minute: _Minute, plan: dict) -> None:
        remaining = self.m.get("siphon_left")
        if remaining is None:
            remaining = min(plan["siphon_l"], self.fuel * 0.6)
        take = min(self.tuning.siphon_rate_lpm, remaining, self.fuel)
        self.fuel -= take
        minute.drained_l = take
        remaining -= take
        self.m["siphon_total"] = self.m.get("siphon_total", 0.0) + take
        if remaining <= 0.5:
            total = self.m.pop("siphon_total")
            self.m.pop("siphon_left", None)
            self.mark("siphon")
            self.event(
                minute,
                EventType.SUSPECTED_DRAIN,
                -total,
                {"engine_on": False, "location": "yard"},
            )
        else:
            self.m["siphon_left"] = remaining

    def _refuel(self, minute: _Minute, rng: random.Random) -> None:
        minute.operation = VehicleOperation.REFUELING
        if "fill" not in self.m:
            target = self.spec.tank_capacity_l * rng.uniform(REFUEL_TARGET_MIN, 1.0)
            billed = max(0.0, target - self.fuel)
            short = 0.0
            if rng.random() < self.tuning.short_fill_probability:
                short = billed * rng.uniform(
                    self.tuning.short_fill_min_fraction, self.tuning.short_fill_max_fraction
                )
            self.m["fill"] = {"billed": billed, "left": billed - short, "short": short}
        fill = self.m["fill"]
        take = min(REFUEL_RATE_LPM, fill["left"])
        self.fuel = min(self.spec.tank_capacity_l, self.fuel + take)
        minute.refuelled_l = take
        fill["left"] -= take
        if fill["left"] <= 0.01:
            delivered = fill["billed"] - fill["short"]
            self.event(minute, EventType.REFILL, delivered, {"billed_l": round(fill["billed"], 1)})
            if fill["short"] > 0:
                self.event(
                    minute,
                    EventType.SHORT_FILL,
                    -fill["short"],
                    {
                        "billed_l": round(fill["billed"], 1),
                        "measured_l": round(delivered, 1),
                    },
                )
            del self.m["fill"]
            self.m["low_fuel"] = False
            then = self.m.pop("after_refuel", "OFF")
            self.m["phase"] = then
            if then == "WARMUP":
                self.m["warm"] = 6

    def _transit(self, minute: _Minute) -> None:
        minute.operation = VehicleOperation(self.m.get("leg_op", "TRANSIT"))
        minute.load = TRANSIT_LOAD if minute.operation == VehicleOperation.TRANSIT else 0.5
        target = self.m["target"]
        step_m = self.m["kmh"] * 1000 / 60
        east, north = local_offset(self.m["lat"], self.m["lon"], target[0], target[1])
        distance = math.hypot(east, north)
        if distance > 1.0:
            self.m["heading"] = bearing_deg(self.m["lat"], self.m["lon"], target[0], target[1])
        if distance <= step_m:
            self.m["lat"], self.m["lon"] = target
            minute.distance_m = distance
            minute.speed_kmh = distance * 60 / 1000
            self._arrive(self.m.pop("then"))
        else:
            ratio = step_m / distance
            self.m["lat"], self.m["lon"] = offset_latlon(
                self.m["lat"], self.m["lon"], east * ratio, north * ratio
            )
            minute.distance_m = step_m
            minute.speed_kmh = self.m["kmh"]

    def _arrive(self, then: str) -> None:
        if then == "WORK":
            self.m["phase"] = "WORK"
        elif then == "DETOUR_STOP":
            self.m["phase"], self.m["stay"] = "DETOUR_STOP", self.plan().get("off_field_stay", 30)
        elif then == "AH_STOP":
            self.m["phase"], self.m["stay"] = "AH_STOP", self.plan().get("after_hours_stay", 30)
        elif then == "HOME":
            if self.fuel < self.spec.tank_capacity_l * 0.4:
                self.m["phase"], self.m["after_refuel"] = "REFUEL", "OFF"
            else:
                self.m["phase"] = "OFF"

    def _work(self, minute: _Minute, minute_of_day: int, plan: dict) -> None:
        capacity = self.spec.tank_capacity_l
        if minute_of_day >= plan["end_min"] or self.fuel < capacity * RETURN_FRACTION:
            if minute_of_day >= plan["end_min"]:
                self.mark("shift_over")
            self.go(self.yard(), "HOME", plan["transit_kmh"])
            self._transit(minute)
            return
        if not self.done("lunch") and minute_of_day >= plan["lunch_min"]:
            self.mark("lunch")
            self.m["phase"] = "LUNCH"
            return
        if (
            "off_field_min" in plan
            and not self.done("off_field")
            and minute_of_day >= plan["off_field_min"]
        ):
            self.mark("off_field")
            target = offset_latlon(
                self.spec.field.latitude,
                self.spec.field.longitude,
                plan["off_field_m"] * math.sin(math.radians(plan["off_field_bearing"])),
                plan["off_field_m"] * math.cos(math.radians(plan["off_field_bearing"])),
            )
            self.go(target, "DETOUR_STOP", plan["transit_kmh"])
            self._transit(minute)
            return

        operation = self.operation()
        profile = OPERATIONS[operation]
        passes = passes_for(self.spec, operation)
        width = implement_width_m(self.spec, operation)
        index = self.m["pass_index"] % len(passes)
        current = passes[index]
        along = self.m["along"] if self.m["along"] is not None else current.start_along_m

        speed = profile.speed_kmh
        step_m = speed * 1000 / 60
        direction = 1.0 if current.end_along_m >= current.start_along_m else -1.0
        remaining = abs(current.end_along_m - along)
        worked = min(step_m, remaining)
        along += direction * worked
        if step_m >= remaining:
            # Headland turn into the next pass; the leftover distance goes on
            # the turn itself, which covers no new ground.
            index = (index + 1) % len(passes)
            along = passes[index].start_along_m
            current = passes[index]
            direction = 1.0 if current.end_along_m >= current.start_along_m else -1.0

        self.m["pass_index"], self.m["along"] = index, along
        self.m["lat"], self.m["lon"] = field_to_latlon(self.spec.field, along, current.across_m)
        heading = self.spec.field.heading_deg + (0.0 if direction > 0 else 180.0)
        self.m["heading"] = heading % 360.0

        minute.operation = operation
        minute.load = profile.load
        minute.speed_kmh = speed
        minute.distance_m = step_m
        minute.area_ha = worked * width / 10_000

    def _burn(self, minute: _Minute) -> None:
        """Burn fuel for the minute, update engine and thermal state."""
        plan = self.plan()
        engine_on = minute.load > 0.0
        if engine_on != self.m["engine_on"]:
            self.event(
                minute,
                EventType.ENGINE_START if engine_on else EventType.ENGINE_STOP,
                None,
                {"operation": minute.operation.value},
            )
            self.m["engine_on"] = engine_on

        norm_lph = fuel_rate_lph(self.spec.engine_kw, minute.load) * plan["efficiency"]
        can_l = norm_lph / 60.0
        true_l = can_l * plan.get("return_line", 1.0) if engine_on else 0.0
        true_l = min(true_l, self.fuel)
        self.fuel -= true_l
        minute.can_l = can_l
        minute.norm_lph = norm_lph

        stats = self.m["stats"]
        stats["can_l"] += can_l
        stats["true_l"] += true_l
        if minute.area_ha > 0:
            stats["work_l"] += can_l
            stats["area_ha"] += minute.area_ha

        if engine_on:
            self.hours += 1 / 60
        target_c = 82.0 + 10.0 * minute.load if engine_on else AMBIENT_C
        tau = 8.0 if engine_on else 40.0
        self.m["coolant"] += (target_c - self.m["coolant"]) / tau

        capacity = self.spec.tank_capacity_l
        if self.fuel < capacity * LOW_FUEL_FRACTION and not self.m["low_fuel"]:
            self.m["low_fuel"] = True
            self.event(
                minute, EventType.LOW_FUEL, None, {"pct": round(self.fuel / capacity * 100, 1)}
            )

    def _field_crossing(self, minute: _Minute) -> None:
        inside = contains(self.spec.field, self.m["lat"], self.m["lon"], FIELD_MARGIN_M)
        if inside != self.m["in_field"]:
            self.m["in_field"] = inside
            self.event(minute, EventType.FIELD_ENTER if inside else EventType.FIELD_EXIT, None, {})
            if not inside and self.m["phase"] == "TRANSIT" and self.m.get("then") == "DETOUR_STOP":
                self.event(
                    minute,
                    EventType.MISUSE,
                    None,
                    {"kind": "off_field", "distance_m": round(self.plan()["off_field_m"])},
                )

    def _close_day(self) -> None:
        """End-of-day reconciliation, emitted on the first minute of the next day."""
        stats = self.m.get("stats") or {}
        plan = self.m["plan"]
        events: list[EventSample] = []
        can_l, true_l = stats.get("can_l", 0.0), stats.get("true_l", 0.0)
        if can_l > 5 and true_l > can_l * 1.12:
            events.append(
                self._close_event(
                    EventType.OVERCONSUMPTION,
                    -(true_l - can_l),
                    {
                        "kind": "return_line",
                        "engine_reported_l": round(can_l, 1),
                        "level_drop_l": round(true_l, 1),
                    },
                )
            )
        operation = VehicleOperation(plan["operation"])
        quota = OPERATIONS[operation].quota_l_per_ha
        area = stats.get("area_ha", 0.0)
        if quota and area > 1.0:
            actual = stats["work_l"] / area
            if actual > quota * self.tuning.quota_tolerance:
                events.append(
                    self._close_event(
                        EventType.OVERCONSUMPTION,
                        -(stats["work_l"] - quota * area),
                        {
                            "kind": "quota",
                            "operation": operation.value,
                            "l_per_ha": round(actual, 2),
                            "quota_l_per_ha": quota,
                            "area_ha": round(area, 2),
                        },
                    )
                )
        self.pending_close = events

    def _close_event(self, kind: EventType, volume: float, detail: dict) -> EventSample:
        return EventSample(
            organisation_id=self.spec.organisation_id,
            vehicle_id=self.spec.id,
            event_type=kind,
            occurred_at=self.moment,
            volume_l=round(volume, 2),
            fuel_level_l=round(self.fuel, 2),
            detail=detail,
        )

    # -- output --

    def reading(self, minute: _Minute, rng: random.Random) -> VehicleReadingSample:
        capacity = self.spec.tank_capacity_l
        moving = minute.speed_kmh > 0.5
        noise = rng.gauss(0.0, SENSOR_NOISE_FRACTION * capacity)
        if moving:
            noise += rng.gauss(0.0, SLOSH_NOISE_FRACTION * capacity)
        measured = max(0.0, min(capacity, self.fuel + noise))
        measured = round(measured / LEVEL_QUANTISATION_L) * LEVEL_QUANTISATION_L

        engine_on = self.m["engine_on"]
        if engine_on:
            rpm = 800 + minute.load * 1400 + rng.gauss(0, 25)
            oil = 180 + 250 * (rpm - 800) / 1400 + rng.gauss(0, 8)
            if self.m["coolant"] < 60:
                oil += 40
        else:
            rpm, oil = 0.0, 0.0

        lat, lon = offset_latlon(
            self.m["lat"], self.m["lon"], rng.gauss(0, GPS_JITTER_M), rng.gauss(0, GPS_JITTER_M)
        )
        return VehicleReadingSample(
            vehicle_id=self.spec.id,
            organisation_id=self.spec.organisation_id,
            time=self.moment,
            latitude=round(lat, 7),
            longitude=round(lon, 7),
            speed_kmh=round(max(0.0, minute.speed_kmh + (rng.gauss(0, 0.4) if moving else 0)), 2),
            heading_deg=round(self.m["heading"], 1),
            engine_on=engine_on,
            rpm=round(max(0.0, rpm), 0),
            fuel_level_l=round(measured, 1),
            fuel_level_pct=round(measured / capacity * 100, 2),
            fuel_rate_lph=round(minute.norm_lph, 2),
            coolant_c=round(self.m["coolant"] + (rng.gauss(0, 0.3) if engine_on else 0), 1),
            oil_kpa=round(max(0.0, oil), 0),
            engine_hours=round(self.hours, 2),
            operation=minute.operation,
            consumed_l=round(minute.can_l, 4),
            distance_m=round(minute.distance_m, 1),
            area_ha=round(minute.area_ha, 4),
        )

    def state(self) -> VehicleState:
        return VehicleState(
            simulated_at=self.moment,
            tick_index=self.tick,
            fuel_level_l=self.fuel,
            engine_hours=self.hours,
            memory=self.m,
        )


def run_vehicle_span(
    spec: VehicleSpec,
    state: VehicleState,
    until: datetime,
    seed: int,
    tuning: VehicleTuning = DEFAULT_VEHICLE,
) -> tuple[VehicleState, list[VehicleReadingSample], list[EventSample]]:
    """Advance one machine minute by minute up to `until`.

    Shared by the backfill and the live ticker, so history and live data
    come from one code path.
    """
    stepper = _Stepper(spec, state, seed, tuning)
    readings: list[VehicleReadingSample] = []
    events: list[EventSample] = []

    while stepper.moment + STEP <= until:
        stepper.moment += STEP
        rng = rng_for(seed, spec.id, stepper.tick, "minute")
        stepper.pending_close = []
        minute = stepper.step(rng)
        events.extend(stepper.pending_close)
        events.extend(minute.events)
        if stepper.m["engine_on"] or stepper.tick % OFF_READING_EVERY_MINUTES == 0 or minute.events:
            readings.append(stepper.reading(minute, rng))
        stepper.tick += 1

    return stepper.state(), readings, events
