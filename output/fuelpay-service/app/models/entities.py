"""Domain model.

Hierarchy: Organisation (tenant) -> Site (a physical location) -> Generator.
Mobile machinery — a tractor carrying its own tank — hangs directly off the
Organisation as a `Vehicle`: it has a yard it returns to, not a site it sits at.

Fuel is two-tier, as a Nigerian bank branch actually runs: a tanker delivers
into site BULK storage (5000 L+), which transfers into each generator's
in-built DAY tank, which feeds the engine. Both tiers are `Tank` rows, and a
site may have more than one bulk tank.

Telemetry splits by what is being measured. Generator state — load, runtime,
engine on/off, GPS — hangs off Generator as `readings`. Fuel level hangs off
Tank as `tank_readings`. Both are TimescaleDB hypertables. Discrete `events`
(deliveries, transfers, suspected drains, signal loss) reference a tank, a
generator, or both.

A tank appears here only because a sensor was installed in it: if it cannot be
sensed, it does not exist to FuelPay. So there are no derived fuel levels, and
a period with no signal is an absence of rows to be shown as a gap — never
interpolated across, since that is exactly when fuel goes missing.

Volumes are double precision, not Numeric: these are sensor readings, not
ledger entries. Anything billing-related should re-derive from events with
explicit rounding rather than trusting a float sum.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class SiteProfile(enum.StrEnum):
    """Drives the load curve and default tank sizing.

    See resources/genset-fuel-consumption-reference.md section 5.
    """

    TELECOM_TOWER = "TELECOM_TOWER"
    OFFICE = "OFFICE"
    RESIDENTIAL = "RESIDENTIAL"
    # The target market: a Nigerian bank branch. Distinct from OFFICE because
    # ATMs and security run 24/7, so the overnight floor never drops to an
    # office's ~20%, and daytime cooling load is heavier.
    BANK_BRANCH = "BANK_BRANCH"


class GeneratorStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class TankKind(enum.StrEnum):
    """Which tier of the fuel path a tank sits in.

    Fuel moves in three hops: tanker -> BULK -> DAY -> engine. A bank site
    normally has one or more shared BULK tanks (5000 L+) feeding the in-built
    DAY tank of each generator.
    """

    BULK = "BULK"
    DAY = "DAY"


class SensorStatus(enum.StrEnum):
    """Reporting state of a tank's fuel sensor.

    A tank with no sensor is not represented in FuelPay at all — if it cannot
    be sensed, it does not exist to us. So this is never "absent": it is the
    difference between a sensor that is reporting and one whose signal is
    lost, which is a very different (and more suspicious) condition.
    """

    ONLINE = "ONLINE"
    STALE = "STALE"
    OFFLINE = "OFFLINE"


class EventType(enum.StrEnum):
    # Retained from the single-tank model: a direct top-up of a generator's
    # tank, and the shape every pre-two-tier row already on disk uses.
    REFILL = "REFILL"
    SUSPECTED_DRAIN = "SUSPECTED_DRAIN"
    LOW_FUEL = "LOW_FUEL"
    ENGINE_START = "ENGINE_START"
    ENGINE_STOP = "ENGINE_STOP"
    # Two-tier fuel path.
    DELIVERY = "DELIVERY"  # tanker -> bulk tank
    TRANSFER = "TRANSFER"  # bulk tank -> day tank
    # Delivered volume fell short of the volume billed. The reconciliation the
    # bulk-tank sensor exists to make possible.
    SHORT_DELIVERY = "SHORT_DELIVERY"
    # Sensor connectivity. SIGNAL_LOSS/RESTORED bracket a telemetry gap;
    # UNVERIFIED_LOSS marks fuel missing across one, which cannot be attributed
    # to consumption or theft without other evidence.
    SIGNAL_LOSS = "SIGNAL_LOSS"
    SIGNAL_RESTORED = "SIGNAL_RESTORED"
    UNVERIFIED_LOSS = "UNVERIFIED_LOSS"
    # Mobile machinery. A vehicle's refuel is a REFILL and a siphon from its
    # tank a SUSPECTED_DRAIN, same as a generator; these cover what only a
    # moving, working machine can do wrong.
    # Burn above the norm: `detail.kind` is "quota" (litres per hectare over
    # the operation's allowance) or "return_line" (fuel diverted from the
    # injection return line, which reads as consumption, not as a level drop).
    OVERCONSUMPTION = "OVERCONSUMPTION"
    # Fuel billed at a refuel exceeded what the tank sensor saw arrive.
    SHORT_FILL = "SHORT_FILL"
    # Use outside the job: `detail.kind` is "after_hours" or "off_field".
    MISUSE = "MISUSE"
    FIELD_ENTER = "FIELD_ENTER"
    FIELD_EXIT = "FIELD_EXIT"


class SimulationStatus(enum.StrEnum):
    """Where an entity's simulated data stream stands.

    A demo entity is created PENDING and only reaches LIVE once its history has
    been generated. The live ticker touches LIVE rows only: advancing a PENDING
    site would give it a cursor at "now", and the backfill would then skip it
    as already simulated, leaving the prospect looking at an empty month.
    """

    PENDING = "PENDING"
    BACKFILLING = "BACKFILLING"
    LIVE = "LIVE"
    FAILED = "FAILED"


class VehicleKind(enum.StrEnum):
    TRACTOR = "TRACTOR"


class VehicleOperation(enum.StrEnum):
    """What a machine is doing. Field operations carry a per-hectare fuel quota;
    the rest are the overhead around them."""

    IDLE = "IDLE"
    TRANSIT = "TRANSIT"
    PLOUGHING = "PLOUGHING"
    HARROWING = "HARROWING"
    SOWING = "SOWING"
    SPRAYING = "SPRAYING"
    TRANSPORT = "TRANSPORT"
    REFUELING = "REFUELING"
    OFF = "OFF"


class Coupon(Base):
    """A PoC code that lets a prospect open a time-limited demo organisation.

    Limits live on the coupon rather than in configuration so sales can hand a
    large prospect a bigger sandbox than a walk-in, and so a leaked code can be
    capped or switched off without a deploy.
    """

    __tablename__ = "coupons"
    __table_args__ = (
        CheckConstraint("redemptions_count <= max_redemptions", name="ck_coupon_redemptions"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Stored upper-case; matched case-insensitively by upper-casing the input.
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(200))
    max_redemptions: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    redemptions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    demo_duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    max_locations: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_tractors: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_generators_per_location: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CouponRedemption(Base):
    """Audit trail of who redeemed what.

    `organisation_id` is SET NULL rather than CASCADE so the record outlives
    the demo organisation it created: purging a prospect's sandbox should not
    erase the fact that the code was used.
    """

    __tablename__ = "coupon_redemptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    coupon_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("coupons.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organisations.id", ondelete="SET NULL")
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(254))
    # SHA-256 of the client address: enough to spot one source hammering the
    # endpoint, without keeping the address itself.
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    # Demo tenants are opened by a coupon and purged after `demo_expires_at`.
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    demo_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    coupon_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("coupons.id", ondelete="SET NULL")
    )
    # Set when a demo is converted into a paying tenant; how coupon
    # conversion is measured.
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sites: Mapped[list["Site"]] = relationship(back_populates="organisation")
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="organisation")


class ApiKey(Base):
    """Only the SHA-256 hash is stored; the plaintext key is shown once on issue.

    `prefix` is the first few plaintext chars, kept so a key can be identified
    in a listing without being reversible.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="default")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organisation: Mapped[Organisation] = relationship(back_populates="api_keys")


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("organisation_id", "name", name="uq_site_org_name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    profile: Mapped[SiteProfile] = mapped_column(
        Enum(SiteProfile, name="site_profile"), nullable=False
    )
    # Fixed installation position. Readings jitter around this, they don't move.
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    address: Mapped[str | None] = mapped_column(String(400))
    simulation_status: Mapped[SimulationStatus] = mapped_column(
        Enum(SimulationStatus, name="simulation_status"),
        nullable=False,
        default=SimulationStatus.LIVE,
        server_default=SimulationStatus.LIVE.value,
    )
    backfill_progress: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    backfill_error: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organisation: Mapped[Organisation] = relationship(back_populates="sites")
    generators: Mapped[list["Generator"]] = relationship(back_populates="site")
    # Both tiers. A site may have several BULK tanks; filter by kind.
    tanks: Mapped[list["Tank"]] = relationship(back_populates="site")


class Generator(Base):
    __tablename__ = "generators"
    __table_args__ = (UniqueConstraint("organisation_id", "serial", name="uq_gen_org_serial"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    serial: Mapped[str] = mapped_column(String(80), nullable=False)

    # Nameplate apparent power. The MVP brief covers 25-100 kVA.
    kva_rating: Mapped[float] = mapped_column(Float, nullable=False)
    # kVA -> kW conversion. 0.8 is the industry standard assumption.
    power_factor: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    tank_capacity_l: Mapped[float] = mapped_column(Float, nullable=False)
    # Refill is triggered below this fraction of capacity.
    reorder_threshold_pct: Mapped[float] = mapped_column(Float, nullable=False, default=25.0)

    status: Mapped[GeneratorStatus] = mapped_column(
        Enum(GeneratorStatus, name="generator_status"),
        nullable=False,
        default=GeneratorStatus.ACTIVE,
    )
    commissioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    site: Mapped[Site] = relationship(back_populates="generators")
    # One in-built tank per generator. A list on the ORM side only because the
    # foreign key lives on `tanks`; enforced single by uq_tank_generator.
    day_tank: Mapped["Tank | None"] = relationship(
        back_populates="generator", uselist=False
    )

    @property
    def rated_kw(self) -> float:
        return self.kva_rating * self.power_factor


class Tank(Base):
    """An instrumented fuel tank — either site bulk storage or a generator's
    in-built day tank.

    Every tank here has a sensor. That is not a modelling convenience but the
    definition: FuelPay knows about a tank because a sensor was installed in
    it, so `sensor_serial` and `calibrated_at` are NOT NULL. An uninstrumented
    tank on the same site is simply invisible to the platform.

    The tank is calibrated to its sensor at commissioning, so readings arrive
    already in litres. There is no raw-count-to-volume curve here; recording
    which sensor produced a series and when it was calibrated is what makes a
    historical reading interpretable after a swap.

    `generator_id` is set for DAY tanks and NULL for BULK tanks, which belong
    to the site and may feed several generators.
    """

    __tablename__ = "tanks"
    __table_args__ = (
        UniqueConstraint("organisation_id", "sensor_serial", name="uq_tank_org_sensor"),
        Index("ix_tanks_site_kind", "site_id", "kind"),
        # A generator has at most one day tank. Partial, because the many BULK
        # rows all have a NULL generator_id and must not collide with it.
        Index(
            "uq_tank_generator",
            "generator_id",
            unique=True,
            postgresql_where=text("generator_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), nullable=False
    )
    # NULL for BULK: a bulk tank serves the site, not one generator.
    generator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generators.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[TankKind] = mapped_column(Enum(TankKind, name="tank_kind"), nullable=False)

    capacity_l: Mapped[float] = mapped_column(Float, nullable=False)
    # Below this fraction the tank is due for replenishment — a delivery for
    # BULK, a transfer for DAY.
    reorder_threshold_pct: Mapped[float] = mapped_column(Float, nullable=False, default=25.0)

    sensor_model: Mapped[str] = mapped_column(String(80), nullable=False)
    sensor_serial: Mapped[str] = mapped_column(String(80), nullable=False)
    calibrated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Denormalised from tank_readings so a fleet listing can show connectivity
    # without a correlated MAX(time) subquery per tank.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    site: Mapped[Site] = relationship(back_populates="tanks")
    generator: Mapped["Generator | None"] = relationship(back_populates="day_tank")


class TankReading(Base):
    """Fuel level sample for one tank. A TimescaleDB hypertable on `time`.

    Kept apart from `readings` rather than folded in as another column: a
    reading in that table is generator telemetry — load, runtime, engine
    state, GPS — none of which a bulk tank has. Sharing the table would leave
    most columns meaningless on every bulk row and force `generator_id`, which
    is part of that table's primary key, to become nullable.

    Every row here was measured. There is no derived-level fallback, because a
    tank without a sensor is not in the system; a period with no sensor signal
    is an absence of rows, and must be rendered as a gap rather than
    interpolated across.
    """

    __tablename__ = "tank_readings"
    __table_args__ = (
        Index("ix_tank_readings_org_time", "organisation_id", "time"),
        Index("ix_tank_readings_tank_time_desc", "tank_id", "time", postgresql_using="btree"),
    )

    tank_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tanks.id", ondelete="CASCADE"), primary_key=True
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    level_l: Mapped[float] = mapped_column(Float, nullable=False)
    level_pct: Mapped[float] = mapped_column(Float, nullable=False)
    # Litres removed since the previous sample, split by cause so rollups stay
    # a plain SUM instead of a window function over level deltas that refills
    # and transfers would corrupt.
    consumed_l: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    transferred_l: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class Reading(Base):
    """Telemetry sample. Becomes a TimescaleDB hypertable partitioned on `time`.

    Timescale requires the partitioning column in every unique index, hence the
    composite (generator_id, time) primary key rather than a surrogate id.

    organisation_id is denormalised onto every row so tenant-scoped time-range
    queries never need to join back through generators -> sites.
    """

    __tablename__ = "readings"
    __table_args__ = (
        Index("ix_readings_org_time", "organisation_id", "time"),
        Index("ix_readings_gen_time_desc", "generator_id", "time", postgresql_using="btree"),
    )

    generator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generators.id", ondelete="CASCADE"), primary_key=True
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    fuel_level_l: Mapped[float] = mapped_column(Float, nullable=False)
    fuel_level_pct: Mapped[float] = mapped_column(Float, nullable=False)
    load_kw: Mapped[float] = mapped_column(Float, nullable=False)
    load_pct: Mapped[float] = mapped_column(Float, nullable=False)
    engine_running: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Litres burned since the previous reading. Makes consumption rollups a
    # plain SUM instead of a window function over level deltas, which would
    # otherwise be corrupted by refills.
    consumed_l: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    runtime_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_org_occurred", "organisation_id", "occurred_at"),
        Index("ix_events_gen_occurred", "generator_id", "occurred_at"),
        Index("ix_events_tank_occurred", "tank_id", "occurred_at"),
        Index("ix_events_vehicle_occurred", "vehicle_id", "occurred_at"),
        # A vehicle event is about the machine and its onboard tank only.
        CheckConstraint(
            "vehicle_id IS NULL OR (generator_id IS NULL AND tank_id IS NULL)",
            name="ck_event_vehicle_exclusive",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    # Nullable since the two-tier model: a tanker DELIVERY into shared bulk
    # storage, or a bulk sensor dropping signal, belongs to the site and to no
    # single generator. Engine and day-tank events still set it.
    generator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generators.id", ondelete="CASCADE")
    )
    # Which tank the event happened to. NULL for engine start/stop, which are
    # properties of the generator rather than of any tank.
    tank_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tanks.id", ondelete="CASCADE"))
    # Set for mobile machinery, whose tank is part of the vehicle rather than a
    # `tanks` row. Exclusive with the two above.
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE")
    )
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, name="event_type"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Signed: positive for a refill, negative for a drain. Null for engine events.
    volume_l: Mapped[float | None] = mapped_column(Float)
    fuel_level_l: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SimulationState(Base):
    """Per-generator cursor for the live ticker.

    Persisted so a restart resumes where it left off instead of replaying or
    skipping. One row per generator.

    Fuel level is deliberately absent: it belongs to a tank now, and lives in
    `tank_simulation_state`.
    """

    __tablename__ = "simulation_state"

    generator_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generators.id", ondelete="CASCADE"), primary_key=True
    )
    simulated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    engine_running: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Monotonic counter feeding the per-tick RNG, so a resumed run does not
    # repeat the random stream it already consumed.
    tick_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TankSimulationState(Base):
    """Per-tank resume cursor: how much fuel is in it and what is happening to it.

    Split from `simulation_state` because a bulk tank has no generator to hang
    state off, and because one bulk tank is shared by several generators — its
    level cannot be a property of any one of them.
    """

    __tablename__ = "tank_simulation_state"

    tank_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tanks.id", ondelete="CASCADE"), primary_key=True
    )
    level_l: Mapped[float] = mapped_column(Float, nullable=False)
    # Set while a multi-tick siphon is in progress: litres still to be removed.
    pending_drain_l: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Ticks left in a simulated signal outage. While positive the tank emits no
    # readings at all — which is exactly what a lost sensor looks like.
    signal_out_ticks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # True level when the signal dropped, so the reconnect can tell whether
    # fuel went missing while nobody was watching.
    level_at_signal_loss_l: Mapped[float | None] = mapped_column(Float)
    # Litres legitimately drawn since the signal dropped, so a reconnect can
    # subtract ordinary consumption before alleging a loss.
    accounted_outflow_l: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Vehicle(Base):
    """A piece of mobile machinery with an instrumented onboard tank.

    Not a Site: a tractor has a yard it returns to and a field it works, and
    neither needs a generator or a fixed tank. The onboard tank is a column
    rather than a `tanks` row because it moves with the machine, and because
    the 1000 L floor that applies to site storage is the wrong rule for a
    150-600 L tractor tank.

    As with site tanks, the fuel sensor is NOT NULL: a machine FuelPay cannot
    sense is not in FuelPay.

    The field is an oriented rectangle centred on (field_latitude,
    field_longitude). That is coarser than a surveyed polygon but enough to
    decide in-field vs. off-field and to lay out working passes.
    """

    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("organisation_id", "serial", name="uq_vehicle_org_serial"),
        UniqueConstraint("organisation_id", "fuel_sensor_serial", name="uq_vehicle_org_sensor"),
        CheckConstraint(
            "tank_capacity_l BETWEEN 100 AND 1000", name="ck_vehicle_tank_capacity"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[VehicleKind] = mapped_column(
        Enum(VehicleKind, name="vehicle_kind"), nullable=False, default=VehicleKind.TRACTOR
    )
    make_model: Mapped[str | None] = mapped_column(String(120))
    serial: Mapped[str] = mapped_column(String(80), nullable=False)
    engine_kw: Mapped[float] = mapped_column(Float, nullable=False)
    tank_capacity_l: Mapped[float] = mapped_column(Float, nullable=False)

    fuel_sensor_model: Mapped[str] = mapped_column(String(80), nullable=False)
    fuel_sensor_serial: Mapped[str] = mapped_column(String(80), nullable=False)
    calibrated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    yard_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    yard_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    field_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    field_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    field_width_m: Mapped[float] = mapped_column(Float, nullable=False)
    field_length_m: Mapped[float] = mapped_column(Float, nullable=False)
    # Bearing of the field's long axis, degrees clockwise from north.
    field_heading_deg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    primary_operation: Mapped[VehicleOperation] = mapped_column(
        Enum(VehicleOperation, name="vehicle_operation"), nullable=False
    )
    # Local hours. Work outside them is what MISUSE(after_hours) flags.
    working_hours_start: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    working_hours_end: Mapped[int] = mapped_column(Integer, nullable=False, default=18)
    # Fixed UTC offset of the machine's locale. Nigeria has no DST, so an
    # offset is exact where a zone name would only add a tzdata dependency.
    utc_offset_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    simulation_status: Mapped[SimulationStatus] = mapped_column(
        Enum(SimulationStatus, name="simulation_status"),
        nullable=False,
        default=SimulationStatus.PENDING,
    )
    backfill_progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    backfill_error: Mapped[str | None] = mapped_column(String(500))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VehicleReading(Base):
    """Telematics sample from one machine. A hypertable on `time` where
    TimescaleDB is installed, like `readings`.

    `fuel_level_l` is the sensor's reading (with noise), not the truth.
    `consumed_l` is litres burned since the previous sample *as the CAN bus
    reports it* — which is the number return-line theft falsifies, and why it
    is stored beside the level rather than derived from it.
    """

    __tablename__ = "vehicle_readings"
    __table_args__ = (
        Index("ix_vehicle_readings_org_time", "organisation_id", "time"),
        Index("ix_vehicle_readings_vehicle_time", "vehicle_id", "time"),
    )

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), primary_key=True
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )

    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    speed_kmh: Mapped[float] = mapped_column(Float, nullable=False)
    heading_deg: Mapped[float] = mapped_column(Float, nullable=False)
    engine_on: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rpm: Mapped[float] = mapped_column(Float, nullable=False)
    fuel_level_l: Mapped[float] = mapped_column(Float, nullable=False)
    fuel_level_pct: Mapped[float] = mapped_column(Float, nullable=False)
    fuel_rate_lph: Mapped[float] = mapped_column(Float, nullable=False)
    coolant_c: Mapped[float] = mapped_column(Float, nullable=False)
    oil_kpa: Mapped[float] = mapped_column(Float, nullable=False)
    engine_hours: Mapped[float] = mapped_column(Float, nullable=False)
    operation: Mapped[VehicleOperation] = mapped_column(
        Enum(VehicleOperation, name="vehicle_operation"), nullable=False
    )
    consumed_l: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    area_ha: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class VehicleSimulationState(Base):
    """Resume cursor for one machine.

    The scalar fields are what every step reads; `memory` holds the day plan
    and the mid-phase details (current pass, waypoint, pending siphon) as JSON,
    because their shape follows the simulator and should not cost a migration
    each time it grows a field.
    """

    __tablename__ = "vehicle_simulation_state"

    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), primary_key=True
    )
    simulated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tick_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fuel_level_l: Mapped[float] = mapped_column(Float, nullable=False)
    engine_hours: Mapped[float] = mapped_column(Float, nullable=False)
    memory: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AdminRole(enum.StrEnum):
    # Everything, including other admins and platform-wide simulator tuning.
    OWNER = "OWNER"
    # Day-to-day operations: coupons, tenants, keys, backfill retries.
    STAFF = "STAFF"


class AdminUser(Base):
    """A person who operates the platform. Not a tenant user: admins sit
    outside every organisation and authenticate on /v1/platform only."""

    __tablename__ = "admin_users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Stored lower-cased; matched by lower-casing the input.
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[AdminRole] = mapped_column(
        Enum(AdminRole, name="admin_role"), nullable=False, default=AdminRole.STAFF
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AdminSession(Base):
    """A signed-in admin. Only the SHA-256 of the token is stored, as with
    API keys; the plaintext goes to the browser once, at login."""

    __tablename__ = "admin_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    admin_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminAuditLog(Base):
    """Who did what on the platform. `actor_label` survives the admin being
    deleted, and names the break-glass key when that was used instead."""

    __tablename__ = "admin_audit_log"
    __table_args__ = (Index("ix_admin_audit_at", "at"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    admin_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    actor_label: Mapped[str] = mapped_column(String(254), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80))
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PlatformSetting(Base):
    """Runtime overrides set from the admin dashboard, e.g. incident tuning.
    Merged over the environment defaults at the start of each simulator run."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_by: Mapped[str | None] = mapped_column(String(254))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
