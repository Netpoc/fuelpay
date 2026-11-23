"""API request and response shapes.

Separate from the SQLAlchemy entities on purpose: the wire format is a contract
with clients and should not shift every time a column is renamed. Volumes are
rounded here rather than in the query so the rounding rule lives in one place.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.entities import (
    EventType,
    GeneratorStatus,
    SensorStatus,
    SiteProfile,
    TankKind,
    VehicleKind,
    VehicleOperation,
)
from app.models.entities import SimulationStatus as StreamStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- fleet ---


class SiteOut(ORMModel):
    id: uuid.UUID
    name: str
    profile: SiteProfile
    latitude: float
    longitude: float
    address: str | None = None


class GeneratorOut(ORMModel):
    id: uuid.UUID
    site_id: uuid.UUID
    name: str
    serial: str
    kva_rating: float
    power_factor: float
    tank_capacity_l: float
    reorder_threshold_pct: float
    status: GeneratorStatus
    commissioned_at: datetime | None = None


# --- tanks ---


class TankOut(ORMModel):
    """An instrumented tank in either storage tier.

    There is no "has a sensor" field: a tank is here because a sensor is in it.
    What varies is whether that sensor is currently reporting, which is what
    `sensor_status` and `last_seen_at` carry.
    """

    id: uuid.UUID
    site_id: uuid.UUID
    generator_id: uuid.UUID | None = Field(
        default=None,
        description="Set for DAY tanks. Null for BULK, which serves the whole site.",
    )
    name: str
    kind: TankKind
    capacity_l: float
    reorder_threshold_pct: float
    sensor_model: str
    sensor_serial: str
    calibrated_at: datetime
    last_seen_at: datetime | None = None


class TankState(TankOut):
    """A tank plus its latest measured level and connectivity."""

    sensor_status: SensorStatus
    level_l: float | None = Field(
        default=None,
        description=(
            "Latest measured level. Null when the sensor has never reported — "
            "never an estimate, since an unobserved tank has no level to give."
        ),
    )
    level_pct: float | None = None
    measured_at: datetime | None = None
    stale_seconds: float | None = Field(
        default=None, description="Age of the latest reading. Null if there is none."
    )


class TankSeriesPoint(BaseModel):
    time: datetime = Field(description="Bucket start, UTC.")
    level_l: float
    level_min_l: float = Field(
        description="Lowest level in the bucket. Preserves a siphon that would "
        "otherwise be averaged away at coarse resolution."
    )
    level_max_l: float
    consumed_l: float
    transferred_l: float
    samples: int


class TankSeries(BaseModel):
    """Chart-ready level history for one tank, oldest first.

    Buckets with no readings are omitted rather than zero-filled: a gap means
    the sensor was not reporting, and a client must render it as a break in the
    line instead of joining across it.
    """

    tank_id: uuid.UUID
    kind: TankKind
    capacity_l: float
    bucket_minutes: int
    start: datetime
    end: datetime
    points: list[TankSeriesPoint]


class DailyTankFlow(BaseModel):
    """One day of fuel movement through a tank, split by cause.

    Every figure is a SUM of recorded movements, never a level delta — a delta
    would net a delivery against the burn that followed it and report neither.
    """

    day: datetime = Field(description="UTC midnight of the bucket.")
    # Burned by the engine (day tanks). Always 0 for bulk, which feeds no engine.
    consumed_l: float
    # Pumped out to a day tank (bulk tanks), or in from bulk (day tanks).
    transferred_l: float
    # Signed positive: fuel arriving from a tanker.
    delivered_l: float
    # Positive magnitude, though events store losses negative.
    drained_l: float
    # Reported unaccounted across a sensor outage. Kept apart from `drained_l`
    # because nobody observed it — it is not established theft.
    unverified_loss_l: float
    # Readings behind the row. A low count means the day is partly unobserved,
    # so the totals above are a floor rather than the truth.
    samples: int


class TankConsumption(BaseModel):
    tank_id: uuid.UUID
    tank_name: str
    kind: TankKind
    capacity_l: float
    days: list[DailyTankFlow] = Field(
        description="ASCENDING by day. Days with no activity are absent."
    )
    total_consumed_l: float
    total_transferred_l: float
    total_delivered_l: float
    total_drained_l: float
    total_unverified_loss_l: float


class SiteFuel(BaseModel):
    """Both tiers of a site's storage, for a fleet overview."""

    site: SiteOut
    bulk: list[TankState]
    day: list[TankState]
    bulk_capacity_l: float
    bulk_level_l: float | None = Field(
        default=None,
        description="Summed across reporting bulk tanks. Null if none are reporting.",
    )
    bulk_level_pct: float | None = None
    # Bulk tanks whose sensor is not currently reporting. Surfaced rather than
    # hidden, because a site total computed over a partial set is misleading.
    bulk_tanks_reporting: int = 0
    bulk_tanks_total: int = 0


class SiteSummary(BaseModel):
    """One site rolled up to a single row — the unit a map pin represents.

    Exists so a fleet map is one request rather than one per site. Every level
    here is summed over *reporting* tanks only, and the reporting/total counts
    ride along so a caller can tell "half empty" from "half unmeasured". A pin
    coloured from a total computed over a dark sensor would be inventing an
    emergency.
    """

    site: SiteOut
    generator_count: int
    running_count: int

    bulk_capacity_l: float
    bulk_level_l: float | None = Field(
        default=None,
        description=(
            "Summed across bulk tanks that have EVER reported. Null if none have. "
            "Read this with `dark_sensors`, not instead of it — see the note there."
        ),
    )
    bulk_level_pct: float | None = None
    bulk_tanks_reporting: int = 0
    bulk_tanks_total: int = 0
    # Strictest reorder line across the tier, so a client can classify the site
    # against the same threshold the tanks themselves carry.
    bulk_reorder_threshold_pct: float = 0.0

    day_capacity_l: float
    day_level_l: float | None = None
    day_level_pct: float | None = None
    day_tanks_reporting: int = 0
    day_tanks_total: int = 0
    day_reorder_threshold_pct: float = 0.0

    dark_sensors: int = Field(
        default=0,
        description=(
            "Tanks in either tier whose sensor has gone quiet (OFFLINE). "
            "INDEPENDENT of the reporting counts above: `*_tanks_reporting` means "
            "'has ever produced a level', this means 'has produced none in the last "
            "hour'. A site can report reporting == total AND dark_sensors == total, "
            "because the levels above are the last ones measured, however old. Treat "
            "any dark sensor as making this site's totals unverified — do not read "
            "reporting == total as proof they are current."
        ),
    )

    consumed_l_24h: float = 0.0
    # Fuel arriving: a tanker DELIVERY into bulk, or a REFILL into a generator's
    # tank. TRANSFER is excluded — bulk -> day moves fuel *within* the site.
    delivered_l_24h: float = 0.0
    # Positive magnitudes, though events store losses negative. Three separate
    # fields because they are three different claims: a drain was observed, a
    # short delivery was measured against a docket, and an unverified loss is
    # fuel missing across an outage that nobody watched. Collapsing them would
    # report unverified loss as established theft.
    drained_l_24h: float = 0.0
    short_delivery_l_24h: float = 0.0
    unverified_loss_l_24h: float = 0.0

    as_of: datetime


class GeneratorDetail(GeneratorOut):
    """A generator plus its live position, derived from the latest reading."""

    site: SiteOut
    day_tank: TankState | None = None
    latest: "ReadingOut | None" = None
    hours_to_empty: float | None = Field(
        default=None,
        description="Projected runtime at the current load. Null when the engine is off.",
    )


# --- telemetry ---


class ReadingOut(ORMModel):
    generator_id: uuid.UUID
    time: datetime
    fuel_level_l: float
    fuel_level_pct: float
    load_kw: float
    load_pct: float
    engine_running: bool
    consumed_l: float
    runtime_minutes: float
    latitude: float
    longitude: float


class ReadingPage(BaseModel):
    """Keyset pagination. Cursors beat OFFSET on a time-series table: OFFSET
    forces the database to walk and discard every skipped row."""

    items: list[ReadingOut]
    next_cursor: datetime | None = Field(
        default=None,
        description="Pass as `before` to fetch the next (older) page. Null at the end.",
    )


class EventOut(ORMModel):
    id: uuid.UUID
    # Null for site-level events under the two-tier model: a tanker DELIVERY
    # into shared bulk storage, or a bulk sensor dropping signal, belongs to
    # the site and to no single generator.
    generator_id: uuid.UUID | None = None
    # Which tank the event happened to. Null for engine start/stop, which are
    # properties of the generator rather than of any tank.
    tank_id: uuid.UUID | None = None
    # Set for mobile machinery; exclusive with the two above.
    vehicle_id: uuid.UUID | None = None
    event_type: EventType
    occurred_at: datetime
    volume_l: float | None = None
    fuel_level_l: float | None = None
    detail: dict


class EventPage(BaseModel):
    items: list[EventOut]
    next_cursor: datetime | None = None


# --- analytics ---


class SeriesPoint(BaseModel):
    """One bucket of a downsampled reading series."""

    time: datetime = Field(description="Bucket start, UTC.")
    fuel_level_l: float = Field(description="Mean reported level across the bucket.")
    fuel_min_l: float = Field(
        description="Lowest level in the bucket. Preserves a siphon that would "
        "otherwise be averaged away at coarse resolution."
    )
    fuel_max_l: float
    load_kw: float
    consumed_l: float = Field(description="Litres burned during the bucket.")
    engine_running: bool = Field(description="True if the engine ran at any point.")
    samples: int


class GeneratorSeries(BaseModel):
    """Chart-ready history for one generator.

    Ascending by time, unlike the paginated readings endpoint — a chart needs a
    left-to-right axis, and reversing thousands of points client-side is work
    nobody should have to remember to do.
    """

    generator_id: uuid.UUID
    bucket_minutes: int
    start: datetime
    end: datetime
    points: list[SeriesPoint]


class DailyConsumption(BaseModel):
    day: datetime
    consumed_l: float
    runtime_hours: float
    refilled_l: float
    drained_l: float


class GeneratorConsumption(BaseModel):
    generator_id: uuid.UUID
    generator_name: str
    days: list[DailyConsumption]
    total_consumed_l: float
    total_refilled_l: float
    total_drained_l: float


class FleetSummary(BaseModel):
    generator_count: int
    running_count: int
    total_capacity_l: float
    total_fuel_l: float
    fill_pct: float
    below_reorder_threshold: int
    consumed_l_24h: float
    refilled_l_24h: float
    drained_l_24h: float
    as_of: datetime


# --- admin ---


class IssueKeyRequest(BaseModel):
    label: str = Field(default="default", max_length=120)


class ApiKeyOut(ORMModel):
    """A key as listed. Never carries the secret."""

    id: uuid.UUID
    prefix: str
    label: str
    created_at: datetime
    revoked_at: datetime | None = None


class IssuedKey(ApiKeyOut):
    """The one and only time the plaintext is ever returned. It is not
    recoverable afterwards — only its SHA-256 hash is stored."""

    api_key: str


# --- simulation control ---


class TickOut(BaseModel):
    """Outcome of one simulation tick."""

    generators: int = Field(description="How many generators were advanced.")
    readings: int
    events: int
    skipped_locked: bool = Field(
        description="True when another process was mid-tick and this one wrote nothing."
    )
    still_catching_up: list[uuid.UUID] = Field(
        default_factory=list,
        description="Generators capped by the per-tick step limit; they remain behind now.",
    )
    ticked_at: datetime


class GeneratorLag(BaseModel):
    generator_id: uuid.UUID
    name: str
    simulated_at: datetime
    lag_seconds: float
    fuel_level_l: float
    engine_running: bool


class DrainRequest(BaseModel):
    """Start a siphon on one generator."""

    generator_id: uuid.UUID
    volume_l: float | None = Field(
        default=None,
        gt=0,
        description="Litres to siphon. Defaults to the configured theft range midpoint, "
        "and is clamped to what the tank actually holds.",
    )
    steps: int | None = Field(
        default=None,
        ge=1,
        le=24,
        description="Simulation steps to run now, so the drain is visible immediately. "
        "Each step is sim_minutes_per_tick of simulated time. Defaults to however "
        "many the siphon pump needs to move the whole volume.",
    )


class LevelRequest(BaseModel):
    """Move a tank to a given level. Provide exactly one of the two measures."""

    generator_id: uuid.UUID
    level_l: float | None = Field(default=None, ge=0)
    level_pct: float | None = Field(default=None, ge=0, le=100)
    steps: int = Field(default=1, ge=1, le=24)


class RefillRequest(BaseModel):
    generator_id: uuid.UUID
    steps: int = Field(default=1, ge=1, le=24)


class SimulateOut(BaseModel):
    """What an injected incident produced."""

    generator_id: uuid.UUID
    steps: int
    readings: int
    events: list[EventType] = Field(description="Event types emitted, in order.")
    fuel_level_l: float
    fuel_level_pct: float
    staged_from_l: float | None = Field(
        default=None,
        description="Set when the request moved the tank before the engine would act — "
        "the level it was moved from. Null means the level change was entirely the "
        "simulation's own doing.",
    )
    simulated_from: datetime
    simulated_to: datetime = Field(
        description="This generator's simulated clock afterwards. It runs ahead of the "
        "fleet until wall-clock catches up, during which the live ticker idles it."
    )


class SimulationStatus(BaseModel):
    """Whether the simulated clock is keeping up with the real one."""

    enabled: bool
    tick_seconds: int
    minutes_per_tick: int
    tracked_generators: int
    max_lag_seconds: float | None = Field(
        default=None, description="Furthest-behind generator. Null when none are tracked."
    )
    generators: list[GeneratorLag]
    as_of: datetime


# --- platform: coupons and demo tenants ---


class CouponLimits(BaseModel):
    demo_duration_days: int = Field(default=14, ge=1, le=90)
    max_locations: int = Field(default=2, ge=0, le=20)
    max_tractors: int = Field(default=3, ge=0, le=20)
    max_generators_per_location: int = Field(default=3, ge=1, le=10)


class CouponCreate(CouponLimits):
    code: str | None = Field(
        default=None,
        min_length=4,
        max_length=40,
        pattern=r"^[A-Za-z0-9-]+$",
        description="Omit to generate one. Matched case-insensitively.",
    )
    label: str | None = Field(default=None, max_length=200)
    max_redemptions: int = Field(default=1, ge=1, le=10_000)
    expires_at: datetime | None = None


class CouponUpdate(BaseModel):
    """Every field optional; only those sent are changed."""

    label: str | None = Field(default=None, max_length=200)
    max_redemptions: int | None = Field(default=None, ge=1, le=10_000)
    expires_at: datetime | None = None
    is_active: bool | None = None
    demo_duration_days: int | None = Field(default=None, ge=1, le=90)
    max_locations: int | None = Field(default=None, ge=0, le=20)
    max_tractors: int | None = Field(default=None, ge=0, le=20)
    max_generators_per_location: int | None = Field(default=None, ge=1, le=10)


class CouponOut(ORMModel):
    id: uuid.UUID
    code: str
    label: str | None = None
    max_redemptions: int
    redemptions_count: int
    expires_at: datetime | None = None
    demo_duration_days: int
    max_locations: int
    max_tractors: int
    max_generators_per_location: int
    is_active: bool
    created_at: datetime


class CouponRedemptionOut(ORMModel):
    id: uuid.UUID
    organisation_id: uuid.UUID | None = Field(
        default=None, description="Null once the demo tenant has been purged."
    )
    company_name: str
    contact_email: str | None = None
    redeemed_at: datetime


class CouponDetail(CouponOut):
    redemptions: list[CouponRedemptionOut]


class DemoOrganisationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    coupon_id: uuid.UUID | None = None
    demo_expires_at: datetime | None = None
    expired: bool
    locations: int
    tractors: int
    created_at: datetime


# --- demo signup ---


class RedeemRequest(BaseModel):
    code: str = Field(min_length=4, max_length=40)
    company_name: str = Field(min_length=2, max_length=200)
    contact_email: str | None = Field(
        default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    )

    @field_validator("company_name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Company name is too short.")
        return value


class OrganisationOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str


class DemoLimits(BaseModel):
    max_locations: int
    max_tractors: int
    max_generators_per_location: int


class RedeemOut(BaseModel):
    """The plaintext key appears here once and is unrecoverable afterwards."""

    api_key: str
    organisation: OrganisationOut
    expires_at: datetime
    limits: DemoLimits


class DemoUsage(BaseModel):
    locations: int
    tractors: int


class DemoEntity(BaseModel):
    type: Literal["location", "tractor"]
    id: uuid.UUID
    name: str
    simulation_status: StreamStatus
    progress: float = Field(description="0-1 share of the history generated so far.")
    error: str | None = None


class DemoStatus(BaseModel):
    organisation: OrganisationOut
    is_demo: bool
    expires_at: datetime | None = None
    days_left: int | None = None
    limits: DemoLimits | None = None
    usage: DemoUsage
    entities: list[DemoEntity]
    generating: bool = Field(description="True while any entity is still backfilling.")


class GeneratorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kva_rating: float = Field(description="One of 25, 30, 40, 50, 60, 75 or 100.")
    day_tank_capacity_l: float = Field(
        ge=1000, le=20_000, description="The generator's in-built tank. 1000 L minimum."
    )
    reorder_threshold_pct: float = Field(default=25.0, ge=5, le=60)


class BulkTankCreate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    capacity_l: float = Field(ge=5000, le=100_000, description="External storage. 5000 L+.")
    reorder_threshold_pct: float = Field(default=35.0, ge=5, le=80)


class LocationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    profile: SiteProfile = SiteProfile.BANK_BRANCH
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str | None = Field(default=None, max_length=400)
    generators: list[GeneratorCreate] = Field(min_length=1, max_length=10)
    bulk_tanks: list[BulkTankCreate] = Field(default_factory=list, max_length=4)


class PointIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class FieldIn(PointIn):
    width_m: float = Field(default=400, ge=150, le=1500)
    length_m: float = Field(default=600, ge=150, le=1500)
    heading_deg: float = Field(
        default=0, ge=0, lt=180, description="Long axis, degrees clockwise from north."
    )


FieldOperation = Literal["PLOUGHING", "HARROWING", "SOWING", "SPRAYING", "TRANSPORT"]


class TractorCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    make_model: str | None = Field(default=None, max_length=120)
    engine_kw: float = Field(default=90, ge=50, le=300)
    tank_capacity_l: float = Field(default=250, ge=150, le=600)
    yard: PointIn
    field: FieldIn
    primary_operation: FieldOperation = "PLOUGHING"
    working_hours_start: int = Field(default=6, ge=0, le=23)
    working_hours_end: int = Field(default=18, ge=1, le=24)

    @model_validator(mode="after")
    def _hours_in_order(self) -> "TractorCreate":
        if self.working_hours_end <= self.working_hours_start:
            raise ValueError("working_hours_end must be after working_hours_start.")
        return self


class ProvisionedOut(BaseModel):
    type: Literal["location", "tractor"]
    id: uuid.UUID
    name: str
    simulation_status: StreamStatus


# --- vehicles ---


class VehicleOut(ORMModel):
    id: uuid.UUID
    name: str
    kind: VehicleKind
    make_model: str | None = None
    serial: str
    engine_kw: float
    tank_capacity_l: float
    fuel_sensor_model: str
    fuel_sensor_serial: str
    calibrated_at: datetime
    yard_latitude: float
    yard_longitude: float
    field_latitude: float
    field_longitude: float
    field_width_m: float
    field_length_m: float
    field_heading_deg: float
    primary_operation: VehicleOperation
    working_hours_start: int
    working_hours_end: int
    utc_offset_hours: int
    simulation_status: StreamStatus
    backfill_progress: float
    last_seen_at: datetime | None = None


class VehicleReadingOut(ORMModel):
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


class VehicleState(VehicleOut):
    """A vehicle with its newest sample, for the map and list views."""

    latest: VehicleReadingOut | None = None


class VehicleTodayStats(BaseModel):
    """Since local midnight."""

    engine_hours: float
    distance_km: float
    area_ha: float
    consumed_l: float
    l_per_ha: float | None = None
    quota_l_per_ha: float | None = None


class VehicleDetail(VehicleState):
    field_polygon: list[tuple[float, float]] = Field(
        description="Field corners as [lat, lon], closed ring."
    )
    today: VehicleTodayStats


class VehicleSeriesPoint(BaseModel):
    time: datetime
    fuel_level_l: float | None = None
    fuel_rate_lph: float | None = None
    rpm: float | None = None
    speed_kmh: float | None = None
    coolant_c: float | None = None
    oil_kpa: float | None = None
    consumed_l: float = 0.0
    area_ha: float = 0.0


class VehicleSeries(BaseModel):
    vehicle_id: uuid.UUID
    bucket_minutes: int
    start: datetime
    end: datetime
    points: list[VehicleSeriesPoint]


class TrackSegment(BaseModel):
    operation: VehicleOperation
    coordinates: list[tuple[float, float]] = Field(description="[lon, lat] pairs, GeoJSON order.")


class VehicleTrack(BaseModel):
    vehicle_id: uuid.UUID
    start: datetime
    end: datetime
    points: int
    segments: list[TrackSegment]


GeneratorDetail.model_rebuild()
