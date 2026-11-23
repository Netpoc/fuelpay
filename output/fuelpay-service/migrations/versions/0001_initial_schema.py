"""Initial schema: tenants, fleet, telemetry, events.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-29

Timescale-specific work is guarded on the extension actually being present, so
this migration also applies cleanly to a stock PostgreSQL instance. Without
TimescaleDB you lose chunk pruning and compression, but every query in the app
is plain SQL and still returns correct results.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# create_type=False: the types are created once, explicitly, below. Left to
# itself SQLAlchemy would emit CREATE TYPE per column that references them and
# the second attempt would fail.
site_profile = postgresql.ENUM(
    "TELECOM_TOWER", "OFFICE", "RESIDENTIAL", name="site_profile", create_type=False
)
generator_status = postgresql.ENUM(
    "ACTIVE", "MAINTENANCE", "DECOMMISSIONED", name="generator_status", create_type=False
)
event_type = postgresql.ENUM(
    "REFILL",
    "SUSPECTED_DRAIN",
    "LOW_FUEL",
    "ENGINE_START",
    "ENGINE_STOP",
    name="event_type",
    create_type=False,
)


def _now_column(name: str) -> sa.Column:
    """A NOT NULL timestamptz defaulting to the transaction's clock."""
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    bind = op.get_bind()

    site_profile.create(bind, checkfirst=True)
    generator_status.create(bind, checkfirst=True)
    event_type.create(bind, checkfirst=True)

    op.create_table(
        "organisations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        _now_column("created_at"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("prefix", sa.String(12), nullable=False),
        sa.Column("label", sa.String(120), nullable=False, server_default="default"),
        _now_column("created_at"),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_organisation_id", "api_keys", ["organisation_id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    op.create_table(
        "sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("profile", site_profile, nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("address", sa.String(400), nullable=True),
        _now_column("created_at"),
        sa.UniqueConstraint("organisation_id", "name", name="uq_site_org_name"),
    )
    op.create_index("ix_sites_organisation_id", "sites", ["organisation_id"])

    op.create_table(
        "generators",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sites.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("serial", sa.String(80), nullable=False),
        sa.Column("kva_rating", sa.Float, nullable=False),
        sa.Column("power_factor", sa.Float, nullable=False, server_default="0.8"),
        sa.Column("tank_capacity_l", sa.Float, nullable=False),
        sa.Column("reorder_threshold_pct", sa.Float, nullable=False, server_default="25.0"),
        sa.Column("status", generator_status, nullable=False, server_default="ACTIVE"),
        sa.Column("commissioned_at", sa.DateTime(timezone=True), nullable=True),
        _now_column("created_at"),
        sa.UniqueConstraint("organisation_id", "serial", name="uq_gen_org_serial"),
    )
    op.create_index("ix_generators_organisation_id", "generators", ["organisation_id"])
    op.create_index("ix_generators_site_id", "generators", ["site_id"])

    op.create_table(
        "readings",
        sa.Column(
            "generator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generators.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fuel_level_l", sa.Float, nullable=False),
        sa.Column("fuel_level_pct", sa.Float, nullable=False),
        sa.Column("load_kw", sa.Float, nullable=False),
        sa.Column("load_pct", sa.Float, nullable=False),
        sa.Column("engine_running", sa.Boolean, nullable=False),
        sa.Column("consumed_l", sa.Float, nullable=False, server_default="0"),
        sa.Column("runtime_minutes", sa.Float, nullable=False, server_default="0"),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
    )
    op.create_index("ix_readings_org_time", "readings", ["organisation_id", "time"])
    op.create_index("ix_readings_gen_time_desc", "readings", ["generator_id", "time"])

    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generators.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("volume_l", sa.Float, nullable=True),
        sa.Column("fuel_level_l", sa.Float, nullable=True),
        sa.Column("detail", postgresql.JSONB, nullable=False, server_default="{}"),
        _now_column("created_at"),
    )
    op.create_index("ix_events_org_occurred", "events", ["organisation_id", "occurred_at"])
    op.create_index("ix_events_gen_occurred", "events", ["generator_id", "occurred_at"])

    op.create_table(
        "simulation_state",
        sa.Column(
            "generator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generators.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("simulated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fuel_level_l", sa.Float, nullable=False),
        sa.Column("engine_running", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("tick_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pending_drain_l", sa.Float, nullable=False, server_default="0"),
        _now_column("updated_at"),
    )

    _apply_timescale()


def _apply_timescale() -> None:
    """Promote `readings` to a hypertable when TimescaleDB is available.

    A 7-day chunk keeps a full fleet-week in one chunk at 5-minute resolution,
    which is the window most dashboard queries ask for.
    """
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
                CREATE EXTENSION IF NOT EXISTS timescaledb;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                PERFORM create_hypertable(
                    'readings',
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

    op.drop_table("simulation_state")
    op.drop_table("events")
    # Dropping a hypertable drops its chunks; no Timescale-specific teardown.
    op.drop_table("readings")
    op.drop_table("generators")
    op.drop_table("sites")
    op.drop_table("api_keys")
    op.drop_table("organisations")

    event_type.drop(bind, checkfirst=True)
    generator_status.drop(bind, checkfirst=True)
    site_profile.drop(bind, checkfirst=True)
