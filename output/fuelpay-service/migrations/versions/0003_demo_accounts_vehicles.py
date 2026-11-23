"""Coupon-gated demo accounts, and mobile machinery.

Revision ID: 0003_demo_accounts_vehicles
Revises: 0002_two_tier_tanks
Create Date: 2026-10-29

Two features that arrive together because the demo flow needs both:

- Coupons, redemptions, and demo flags on organisations. A prospect redeems a
  PoC code to open a time-limited tenant, which is purged after expiry.
- Vehicles (tractors) with their own telematics series and resume cursor. A
  vehicle carries its tank, so the onboard tank is a column, and the 1000 L
  floor that governs site storage does not apply to it.

`simulation_status` lands on sites and vehicles so the live ticker can skip an
entity whose history is still being generated. Existing sites default to LIVE
so the seeded fleet keeps ticking unchanged.

As in 0001/0002, Timescale work is guarded on the extension being present.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_demo_accounts_vehicles"
down_revision: str | None = "0002_two_tier_tanks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_EVENT_TYPES = ("OVERCONSUMPTION", "SHORT_FILL", "MISUSE", "FIELD_ENTER", "FIELD_EXIT")

simulation_status = postgresql.ENUM(
    "PENDING", "BACKFILLING", "LIVE", "FAILED", name="simulation_status", create_type=False
)
vehicle_kind = postgresql.ENUM("TRACTOR", name="vehicle_kind", create_type=False)
vehicle_operation = postgresql.ENUM(
    "IDLE",
    "TRANSIT",
    "PLOUGHING",
    "HARROWING",
    "SOWING",
    "SPRAYING",
    "TRANSPORT",
    "REFUELING",
    "OFF",
    name="vehicle_operation",
    create_type=False,
)


def _now_column(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _uuid_fk(name: str, target: str, ondelete: str, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
    )


def upgrade() -> None:
    bind = op.get_bind()

    # Safe inside the migration transaction on PG 12+, provided nothing in
    # this same transaction uses the new values — nothing here does.
    for value in NEW_EVENT_TYPES:
        op.execute(f"ALTER TYPE event_type ADD VALUE IF NOT EXISTS '{value}'")

    simulation_status.create(bind, checkfirst=True)
    vehicle_kind.create(bind, checkfirst=True)
    vehicle_operation.create(bind, checkfirst=True)

    # --- coupons ---------------------------------------------------------
    op.create_table(
        "coupons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False, unique=True),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("max_redemptions", sa.Integer, nullable=False, server_default="1"),
        sa.Column("redemptions_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("demo_duration_days", sa.Integer, nullable=False, server_default="14"),
        sa.Column("max_locations", sa.Integer, nullable=False, server_default="2"),
        sa.Column("max_tractors", sa.Integer, nullable=False, server_default="3"),
        sa.Column("max_generators_per_location", sa.Integer, nullable=False, server_default="3"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        _now_column("created_at"),
        sa.CheckConstraint("redemptions_count <= max_redemptions", name="ck_coupon_redemptions"),
    )

    # --- organisations gain demo flags ----------------------------------
    op.add_column(
        "organisations",
        sa.Column("is_demo", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "organisations", sa.Column("demo_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("organisations", _uuid_fk("coupon_id", "coupons.id", "SET NULL", nullable=True))
    op.create_index("ix_organisations_demo_expires_at", "organisations", ["demo_expires_at"])

    op.create_table(
        "coupon_redemptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _uuid_fk("coupon_id", "coupons.id", "RESTRICT"),
        # SET NULL: the audit record outlives the purged demo tenant.
        _uuid_fk("organisation_id", "organisations.id", "SET NULL", nullable=True),
        sa.Column("company_name", sa.String(200), nullable=False),
        sa.Column("contact_email", sa.String(254), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        _now_column("redeemed_at"),
    )
    op.create_index("ix_coupon_redemptions_coupon_id", "coupon_redemptions", ["coupon_id"])

    # --- sites gain a stream status -------------------------------------
    op.add_column(
        "sites",
        sa.Column("simulation_status", simulation_status, nullable=False, server_default="LIVE"),
    )
    op.add_column(
        "sites", sa.Column("backfill_progress", sa.Float, nullable=False, server_default="1")
    )
    op.add_column("sites", sa.Column("backfill_error", sa.String(500), nullable=True))

    # --- vehicles --------------------------------------------------------
    op.create_table(
        "vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _uuid_fk("organisation_id", "organisations.id", "CASCADE"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", vehicle_kind, nullable=False, server_default="TRACTOR"),
        sa.Column("make_model", sa.String(120), nullable=True),
        sa.Column("serial", sa.String(80), nullable=False),
        sa.Column("engine_kw", sa.Float, nullable=False),
        sa.Column("tank_capacity_l", sa.Float, nullable=False),
        sa.Column("fuel_sensor_model", sa.String(80), nullable=False),
        sa.Column("fuel_sensor_serial", sa.String(80), nullable=False),
        sa.Column("calibrated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("yard_latitude", sa.Float, nullable=False),
        sa.Column("yard_longitude", sa.Float, nullable=False),
        sa.Column("field_latitude", sa.Float, nullable=False),
        sa.Column("field_longitude", sa.Float, nullable=False),
        sa.Column("field_width_m", sa.Float, nullable=False),
        sa.Column("field_length_m", sa.Float, nullable=False),
        sa.Column("field_heading_deg", sa.Float, nullable=False, server_default="0"),
        sa.Column("primary_operation", vehicle_operation, nullable=False),
        sa.Column("working_hours_start", sa.Integer, nullable=False, server_default="6"),
        sa.Column("working_hours_end", sa.Integer, nullable=False, server_default="18"),
        sa.Column("utc_offset_hours", sa.Integer, nullable=False, server_default="1"),
        sa.Column("simulation_status", simulation_status, nullable=False, server_default="PENDING"),
        sa.Column("backfill_progress", sa.Float, nullable=False, server_default="0"),
        sa.Column("backfill_error", sa.String(500), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        _now_column("created_at"),
        sa.UniqueConstraint("organisation_id", "serial", name="uq_vehicle_org_serial"),
        sa.UniqueConstraint("organisation_id", "fuel_sensor_serial", name="uq_vehicle_org_sensor"),
        sa.CheckConstraint("tank_capacity_l BETWEEN 100 AND 1000", name="ck_vehicle_tank_capacity"),
    )
    op.create_index("ix_vehicles_organisation_id", "vehicles", ["organisation_id"])

    op.create_table(
        "vehicle_readings",
        sa.Column(
            "vehicle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        _uuid_fk("organisation_id", "organisations.id", "CASCADE"),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("speed_kmh", sa.Float, nullable=False),
        sa.Column("heading_deg", sa.Float, nullable=False),
        sa.Column("engine_on", sa.Boolean, nullable=False),
        sa.Column("rpm", sa.Float, nullable=False),
        sa.Column("fuel_level_l", sa.Float, nullable=False),
        sa.Column("fuel_level_pct", sa.Float, nullable=False),
        sa.Column("fuel_rate_lph", sa.Float, nullable=False),
        sa.Column("coolant_c", sa.Float, nullable=False),
        sa.Column("oil_kpa", sa.Float, nullable=False),
        sa.Column("engine_hours", sa.Float, nullable=False),
        sa.Column("operation", vehicle_operation, nullable=False),
        sa.Column("consumed_l", sa.Float, nullable=False, server_default="0"),
        sa.Column("distance_m", sa.Float, nullable=False, server_default="0"),
        sa.Column("area_ha", sa.Float, nullable=False, server_default="0"),
    )
    op.create_index("ix_vehicle_readings_org_time", "vehicle_readings", ["organisation_id", "time"])
    op.create_index("ix_vehicle_readings_vehicle_time", "vehicle_readings", ["vehicle_id", "time"])

    op.create_table(
        "vehicle_simulation_state",
        sa.Column(
            "vehicle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("simulated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tick_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fuel_level_l", sa.Float, nullable=False),
        sa.Column("engine_hours", sa.Float, nullable=False),
        sa.Column(
            "memory",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        _now_column("updated_at"),
    )

    # --- events can belong to a vehicle ---------------------------------
    op.add_column("events", _uuid_fk("vehicle_id", "vehicles.id", "CASCADE", nullable=True))
    op.create_index("ix_events_vehicle_occurred", "events", ["vehicle_id", "occurred_at"])
    op.create_check_constraint(
        "ck_event_vehicle_exclusive",
        "events",
        "vehicle_id IS NULL OR (generator_id IS NULL AND tank_id IS NULL)",
    )

    _apply_timescale()


def _apply_timescale() -> None:
    """Promote `vehicle_readings` to a hypertable, same 7-day chunk as the others."""
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                PERFORM create_hypertable(
                    'vehicle_readings',
                    'time',
                    chunk_time_interval => INTERVAL '7 days',
                    migrate_data => TRUE,
                    if_not_exists => TRUE
                );
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Vehicle events go with the column; nothing else can own them.
    op.drop_constraint("ck_event_vehicle_exclusive", "events", type_="check")
    op.drop_index("ix_events_vehicle_occurred", table_name="events")
    op.execute("DELETE FROM events WHERE vehicle_id IS NOT NULL")
    op.drop_column("events", "vehicle_id")

    op.drop_table("vehicle_simulation_state")
    op.drop_table("vehicle_readings")
    op.drop_table("vehicles")

    op.drop_column("sites", "backfill_error")
    op.drop_column("sites", "backfill_progress")
    op.drop_column("sites", "simulation_status")

    op.drop_table("coupon_redemptions")
    op.drop_index("ix_organisations_demo_expires_at", table_name="organisations")
    op.drop_column("organisations", "coupon_id")
    op.drop_column("organisations", "demo_expires_at")
    op.drop_column("organisations", "is_demo")
    op.drop_table("coupons")

    vehicle_operation.drop(bind, checkfirst=True)
    vehicle_kind.drop(bind, checkfirst=True)
    simulation_status.drop(bind, checkfirst=True)

    # PostgreSQL cannot remove enum values; event_type keeps the vehicle
    # types, unreferenced after this point.
