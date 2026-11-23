"""Wire shapes for the platform admin API (`/v1/platform`).

Kept apart from `app.schemas`, which is the tenant-facing contract: admin
responses carry cross-tenant fields (slugs, key prefixes, audit actors) that
must never leak into a tenant schema by accident.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.entities import AdminRole
from app.models.entities import SimulationStatus as StreamStatus
from app.schemas import CouponOut

TenantKind = Literal["real", "demo", "expired"]


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth ---


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class AdminOut(_ORM):
    id: uuid.UUID | None = None
    email: str
    name: str
    role: AdminRole
    is_active: bool = True
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class LoginOut(BaseModel):
    """The token appears here once."""

    token: str
    expires_at: datetime
    admin: AdminOut


class MeOut(BaseModel):
    admin: AdminOut
    break_glass: bool = False


# --- admins ---


class AdminCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=200)
    role: AdminRole = AdminRole.STAFF


class AdminUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: AdminRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=200)


class AuditOut(_ORM):
    id: uuid.UUID
    actor_label: str
    action: str
    target_type: str | None = None
    target_id: str | None = None
    detail: dict
    at: datetime


class AuditPage(BaseModel):
    items: list[AuditOut]
    next_cursor: datetime | None = None


# --- coupons ---


class CouponWithUsage(CouponOut):
    conversions: int = Field(description="Demos opened with this code that became customers.")


# --- tenants ---


class TenantRow(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    kind: TenantKind
    created_at: datetime
    demo_expires_at: datetime | None = None
    converted_at: datetime | None = None
    coupon_code: str | None = None
    sites: int
    generators: int
    tractors: int
    active_keys: int
    last_reading_at: datetime | None = None


class TenantKeyOut(_ORM):
    id: uuid.UUID
    prefix: str
    label: str
    created_at: datetime
    revoked_at: datetime | None = None


class TenantSiteOut(BaseModel):
    id: uuid.UUID
    name: str
    profile: str
    generators: int
    simulation_status: StreamStatus
    backfill_error: str | None = None


class TenantVehicleOut(BaseModel):
    id: uuid.UUID
    name: str
    serial: str
    simulation_status: StreamStatus
    last_seen_at: datetime | None = None
    backfill_error: str | None = None


class TenantDetail(TenantRow):
    contact_email: str | None = None
    site_list: list[TenantSiteOut]
    vehicle_list: list[TenantVehicleOut]
    keys: list[TenantKeyOut]


class TenantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str | None = Field(default=None, min_length=2, max_length=60, pattern=r"^[a-z0-9-]+$")
    key_label: str = Field(default="primary", max_length=120)

    @field_validator("name")
    @classmethod
    def _tidy(cls, value: str) -> str:
        return " ".join(value.split())


class IssuedTenantKey(TenantKeyOut):
    api_key: str


class TenantCreated(BaseModel):
    tenant: TenantRow
    key: IssuedTenantKey


class KeyCreate(BaseModel):
    label: str = Field(default="default", max_length=120)


class ExtendRequest(BaseModel):
    days: int = Field(ge=1, le=90)


class PurgeRequest(BaseModel):
    """The organisation's exact name, typed by a human: a guard against
    purging the wrong row from a list of similar ones."""

    confirm_name: str


# --- overview ---


class DayCount(BaseModel):
    day: datetime
    count: int


class IncidentCount(BaseModel):
    event_type: str
    count: int


class TenantIncidents(BaseModel):
    organisation_id: uuid.UUID
    name: str
    count: int


class Overview(BaseModel):
    tenants_real: int
    demos_active: int
    demos_expiring_3d: int
    demos_expired: int
    conversions_30d: int
    redemptions_30d: int
    conversion_rate: float | None = Field(
        default=None, description="Converted demos / redemptions, over 30 days."
    )
    redemptions_by_day: list[DayCount]
    readings_24h: int
    incidents_24h: list[IncidentCount]
    incidents_by_tenant_24h: list[TenantIncidents]
    as_of: datetime


# --- system ---


class BackfillItem(BaseModel):
    kind: Literal["location", "tractor"]
    id: uuid.UUID
    name: str
    organisation: str
    simulation_status: StreamStatus
    progress: float
    error: str | None = None


class TableSize(BaseModel):
    name: str
    bytes: int


class TickSummary(BaseModel):
    started_at: datetime
    sites: int
    generators: int
    vehicles: int
    readings: int
    vehicle_readings: int
    events: int
    skipped_locked: bool


class SystemStatus(BaseModel):
    sim_enabled: bool
    tick_seconds: int
    max_lag_seconds: float | None = None
    last_tick: TickSummary | None = None
    backfills: list[BackfillItem]
    database_bytes: int
    tables: list[TableSize]
    disk_total_bytes: int
    disk_free_bytes: int
    as_of: datetime


class TuningOut(BaseModel):
    effective: dict[str, dict]
    overrides: dict[str, dict]
    defaults: dict[str, dict]


class TuningUpdate(BaseModel):
    """The complete set of overrides. Anything omitted reverts to default."""

    overrides: dict[str, dict]
