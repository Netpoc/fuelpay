"""The platform at a glance: tenants, demo funnel, data volume, incidents."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_schemas import DayCount, IncidentCount, Overview, TenantIncidents
from app.db import get_session
from app.models.entities import (
    CouponRedemption,
    Event,
    EventType,
    Organisation,
    Reading,
    TankReading,
    VehicleReading,
)
from app.services.admin_auth import AdminActor, require_platform_admin

router = APIRouter()

# What an operator would call an incident: fuel lost or misused. Engine
# transitions, transfers and field crossings are routine and excluded.
INCIDENT_TYPES = (
    EventType.SUSPECTED_DRAIN,
    EventType.SHORT_DELIVERY,
    EventType.UNVERIFIED_LOSS,
    EventType.SHORT_FILL,
    EventType.OVERCONSUMPTION,
    EventType.MISUSE,
)


def conversion_rate(conversions: int, redemptions: int) -> float | None:
    return round(conversions / redemptions, 4) if redemptions else None


def fill_days(rows: list[tuple[datetime, int]], days: int, today: datetime) -> list[DayCount]:
    """One entry per day, zeros included, oldest first — a chart of signups
    must show the quiet days, not skip them."""
    counts = {day.date(): count for day, count in rows}
    start = today.date() - timedelta(days=days - 1)
    out = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        out.append(
            DayCount(
                day=datetime(day.year, day.month, day.day, tzinfo=UTC), count=counts.get(day, 0)
            )
        )
    return out


async def _count(session: AsyncSession, query) -> int:
    return int((await session.execute(query)).scalar_one() or 0)


@router.get("/overview", response_model=Overview, summary="Platform overview")
async def overview(
    _: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> Overview:
    now = datetime.now(UTC)
    since_30d = now - timedelta(days=30)
    since_24h = now - timedelta(hours=24)
    org = select(func.count()).select_from(Organisation)

    tenants_real = await _count(session, org.where(Organisation.is_demo.is_(False)))
    demos_active = await _count(
        session, org.where(Organisation.is_demo.is_(True), Organisation.demo_expires_at > now)
    )
    demos_expiring = await _count(
        session,
        org.where(
            Organisation.is_demo.is_(True),
            Organisation.demo_expires_at > now,
            Organisation.demo_expires_at <= now + timedelta(days=3),
        ),
    )
    demos_expired = await _count(
        session, org.where(Organisation.is_demo.is_(True), Organisation.demo_expires_at <= now)
    )
    conversions = await _count(session, org.where(Organisation.converted_at >= since_30d))
    redemptions = await _count(
        session,
        select(func.count())
        .select_from(CouponRedemption)
        .where(CouponRedemption.redeemed_at >= since_30d),
    )

    day = func.date_trunc("day", CouponRedemption.redeemed_at)
    by_day = (
        await session.execute(
            select(day, func.count())
            .where(CouponRedemption.redeemed_at >= now - timedelta(days=30))
            .group_by(day)
        )
    ).all()

    readings = 0
    for model in (Reading, TankReading, VehicleReading):
        readings += await _count(
            session, select(func.count()).select_from(model).where(model.time >= since_24h)
        )

    incident_where = (Event.occurred_at >= since_24h, Event.event_type.in_(INCIDENT_TYPES))
    incidents = (
        await session.execute(
            select(Event.event_type, func.count())
            .where(*incident_where)
            .group_by(Event.event_type)
            .order_by(func.count().desc())
        )
    ).all()
    by_tenant = (
        await session.execute(
            select(Organisation.id, Organisation.name, func.count())
            .join(Event, Event.organisation_id == Organisation.id)
            .where(*incident_where)
            .group_by(Organisation.id, Organisation.name)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()

    return Overview(
        tenants_real=tenants_real,
        demos_active=demos_active,
        demos_expiring_3d=demos_expiring,
        demos_expired=demos_expired,
        conversions_30d=conversions,
        redemptions_30d=redemptions,
        conversion_rate=conversion_rate(conversions, redemptions),
        redemptions_by_day=fill_days(list(by_day), 30, now),
        readings_24h=readings,
        incidents_24h=[IncidentCount(event_type=t.value, count=n) for t, n in incidents],
        incidents_by_tenant_24h=[
            TenantIncidents(organisation_id=oid, name=name, count=n) for oid, name, n in by_tenant
        ],
        as_of=now,
    )
