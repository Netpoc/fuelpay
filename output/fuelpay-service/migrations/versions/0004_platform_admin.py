"""Platform admin: operator accounts, sessions, audit log, runtime settings.

Revision ID: 0004_platform_admin
Revises: 0003_demo_accounts_vehicles
Create Date: 2026-10-29

Admins sit outside tenancy: they run the platform (coupons, tenants, the
simulator) and authenticate only on /v1/platform. The single
FUELPAY_PLATFORM_ADMIN_KEY remains as a break-glass credential.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_platform_admin"
down_revision: str | None = "0003_demo_accounts_vehicles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

admin_role = postgresql.ENUM("OWNER", "STAFF", name="admin_role", create_type=False)


def _now(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    admin_role.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "organisations", sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "admin_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", admin_role, nullable=False, server_default="STAFF"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        _now("created_at"),
    )

    op.create_table(
        "admin_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        _now("created_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_admin_sessions_admin_user_id", "admin_sessions", ["admin_user_id"])

    op.create_table(
        "admin_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_label", sa.String(254), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=True),
        sa.Column("target_id", sa.String(80), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        _now("at"),
    )
    op.create_index("ix_admin_audit_at", "admin_audit_log", ["at"])

    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("value", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_by", sa.String(254), nullable=True),
        _now("updated_at"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
    op.drop_table("admin_audit_log")
    op.drop_table("admin_sessions")
    op.drop_table("admin_users")
    op.drop_column("organisations", "converted_at")
    admin_role.drop(op.get_bind(), checkfirst=True)
