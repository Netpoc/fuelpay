"""Two-tier fuel storage: instrumented tanks, tank readings, bank profile.

Revision ID: 0002_two_tier_tanks
Revises: 0001_initial
Create Date: 2026-08-07

Models the fuel path a Nigerian bank branch actually runs: a tanker delivers
into site bulk storage (5000 L+), which transfers into each generator's
in-built day tank, which feeds the engine. Both tiers become `tanks` rows; a
site may have several bulk tanks.

Fuel level moves out of `readings` and into `tank_readings`, because level is
now a property of a tank rather than of a generator. `readings` keeps the
columns that genuinely belong to the engine (load, runtime, GPS) and retains
its own `fuel_level_l` so existing single-tank history stays readable.

Every tank has a sensor by definition — an uninstrumented tank is invisible to
FuelPay — so the sensor columns are NOT NULL. Tanks are calibrated to their
sensor at commissioning, so readings arrive in litres and no raw-count
conversion is stored.

As in 0001, Timescale work is guarded on the extension being present so this
applies cleanly to stock PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_two_tier_tanks"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Added in this revision; the enum itself already exists from 0001.
NEW_EVENT_TYPES = (
    "DELIVERY",
    "TRANSFER",
    "SHORT_DELIVERY",
    "SIGNAL_LOSS",
    "SIGNAL_RESTORED",
    "UNVERIFIED_LOSS",
)

tank_kind = postgresql.ENUM("BULK", "DAY", name="tank_kind", create_type=False)


def _now_column(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    bind = op.get_bind()

    # --- enum extensions -------------------------------------------------
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older
    # servers, but Alembic's default transactional DDL is fine from PG 12 on,
    # which is well below the 17 this targets.
    op.execute("ALTER TYPE site_profile ADD VALUE IF NOT EXISTS 'BANK_BRANCH'")
    for value in NEW_EVENT_TYPES:
        op.execute(f"ALTER TYPE event_type ADD VALUE IF NOT EXISTS '{value}'")

    tank_kind.create(bind, checkfirst=True)

    # --- tanks -----------------------------------------------------------
    op.create_table(
        "tanks",
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
        # NULL for BULK: bulk storage serves the site, not one generator.
        sa.Column(
            "generator_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generators.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", tank_kind, nullable=False),
        sa.Column("capacity_l", sa.Float, nullable=False),
        sa.Column("reorder_threshold_pct", sa.Float, nullable=False, server_default="25"),
        sa.Column("sensor_model", sa.String(80), nullable=False),
        sa.Column("sensor_serial", sa.String(80), nullable=False),
        sa.Column("calibrated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        _now_column("created_at"),
        sa.UniqueConstraint("organisation_id", "sensor_serial", name="uq_tank_org_sensor"),
    )
    op.create_index("ix_tanks_organisation_id", "tanks", ["organisation_id"])
    op.create_index("ix_tanks_site_kind", "tanks", ["site_id", "kind"])
    # Partial: every BULK row has a NULL generator_id and must not collide.
    op.create_index(
        "uq_tank_generator",
        "tanks",
        ["generator_id"],
        unique=True,
        postgresql_where=sa.text("generator_id IS NOT NULL"),
    )

    # --- tank_readings ---------------------------------------------------
    op.create_table(
        "tank_readings",
        sa.Column(
            "tank_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tanks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("time", sa.DateTime(timezone=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("level_l", sa.Float, nullable=False),
        sa.Column("level_pct", sa.Float, nullable=False),
        sa.Column("consumed_l", sa.Float, nullable=False, server_default="0"),
        sa.Column("transferred_l", sa.Float, nullable=False, server_default="0"),
    )
    op.create_index("ix_tank_readings_org_time", "tank_readings", ["organisation_id", "time"])
    op.create_index("ix_tank_readings_tank_time_desc", "tank_readings", ["tank_id", "time"])

    # --- events gain a tank, and lose the generator requirement ----------
    op.add_column(
        "events",
        sa.Column(
            "tank_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tanks.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    # A tanker delivery into shared bulk storage belongs to no one generator.
    op.alter_column("events", "generator_id", existing_type=postgresql.UUID(), nullable=True)
    op.create_index("ix_events_tank_occurred", "events", ["tank_id", "occurred_at"])

    # --- simulation state follows the fuel ------------------------------
    # Fuel now lives in tanks, so the resume cursor splits: `simulation_state`
    # keeps what belongs to the engine, and per-tank levels move to their own
    # table (a bulk tank has no generator to hang state off).
    op.drop_column("simulation_state", "fuel_level_l")
    op.drop_column("simulation_state", "pending_drain_l")

    op.create_table(
        "tank_simulation_state",
        sa.Column(
            "tank_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tanks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("level_l", sa.Float, nullable=False),
        # Litres still to be removed by an in-progress siphon.
        sa.Column("pending_drain_l", sa.Float, nullable=False, server_default="0"),
        # Ticks left in a simulated signal outage. While positive the tank
        # emits no readings at all, which is what a lost sensor looks like.
        sa.Column("signal_out_ticks", sa.Integer, nullable=False, server_default="0"),
        # True level when the signal dropped, so the reconnect can decide
        # whether fuel went missing while nobody was watching.
        sa.Column("level_at_signal_loss_l", sa.Float, nullable=True),
        # Litres legitimately drawn since the signal dropped, so a reconnect
        # can subtract ordinary consumption before alleging a loss.
        sa.Column("accounted_outflow_l", sa.Float, nullable=False, server_default="0"),
        _now_column("updated_at"),
    )

    _apply_timescale()


def _apply_timescale() -> None:
    """Promote `tank_readings` to a hypertable when TimescaleDB is available.

    Same 7-day chunk as `readings` in 0001: the two are queried over the same
    dashboard windows and often joined on time, so matching the chunk boundary
    keeps pruning effective on both sides.
    """
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                PERFORM create_hypertable(
                    'tank_readings',
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

    op.drop_table("tank_simulation_state")
    op.add_column(
        "simulation_state",
        sa.Column("fuel_level_l", sa.Float, nullable=False, server_default="0"),
    )
    op.add_column(
        "simulation_state",
        sa.Column("pending_drain_l", sa.Float, nullable=False, server_default="0"),
    )

    op.drop_index("ix_events_tank_occurred", table_name="events")
    # Rows added under the two-tier model may legitimately have no generator,
    # so they must go before the column can be NOT NULL again.
    op.execute("DELETE FROM events WHERE generator_id IS NULL")
    op.alter_column("events", "generator_id", existing_type=postgresql.UUID(), nullable=False)
    op.drop_column("events", "tank_id")

    op.drop_table("tank_readings")
    op.drop_table("tanks")
    tank_kind.drop(bind, checkfirst=True)

    # PostgreSQL cannot remove a value from an enum; site_profile and
    # event_type keep BANK_BRANCH and the two-tier event types. They are
    # unreferenced after this point, which is harmless.
