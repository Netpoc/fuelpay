"""Every organisation on the platform, real and demo, and its API keys."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import ColumnElement, and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_schemas import (
    ExtendRequest,
    IssuedTenantKey,
    KeyCreate,
    PurgeRequest,
    TenantCreate,
    TenantCreated,
    TenantDetail,
    TenantKeyOut,
    TenantKind,
    TenantRow,
    TenantSiteOut,
    TenantVehicleOut,
)
from app.auth import generate_key
from app.db import get_session
from app.models.entities import (
    ApiKey,
    Coupon,
    CouponRedemption,
    Generator,
    Organisation,
    Reading,
    Site,
    Vehicle,
    VehicleReading,
)
from app.services.admin_auth import AdminActor, audit, require_platform_admin
from app.services.provisioning import slugify

router = APIRouter(prefix="/tenants")


def tenant_kind(org: Organisation, now: datetime) -> TenantKind:
    if not org.is_demo:
        return "real"
    if org.demo_expires_at is not None and org.demo_expires_at <= now:
        return "expired"
    return "demo"


def _kind_filter(kind: TenantKind, now: datetime) -> ColumnElement[bool]:
    if kind == "real":
        return Organisation.is_demo.is_(False)
    if kind == "expired":
        return and_(Organisation.is_demo.is_(True), Organisation.demo_expires_at <= now)
    return and_(Organisation.is_demo.is_(True), Organisation.demo_expires_at > now)


def _counts():
    """Correlated per-organisation counts, as scalar subqueries."""
    sites = select(func.count()).where(Site.organisation_id == Organisation.id).scalar_subquery()
    generators = (
        select(func.count()).where(Generator.organisation_id == Organisation.id).scalar_subquery()
    )
    tractors = (
        select(func.count()).where(Vehicle.organisation_id == Organisation.id).scalar_subquery()
    )
    keys = (
        select(func.count())
        .where(ApiKey.organisation_id == Organisation.id, ApiKey.revoked_at.is_(None))
        .scalar_subquery()
    )
    # Index-backed (org, time) lookups, bounded to the last two days so a
    # dormant tenant does not scan its whole history to report "none".
    since = datetime.now(UTC) - timedelta(days=2)
    last_gen = (
        select(func.max(Reading.time))
        .where(Reading.organisation_id == Organisation.id, Reading.time >= since)
        .scalar_subquery()
    )
    last_vehicle = (
        select(func.max(VehicleReading.time))
        .where(VehicleReading.organisation_id == Organisation.id, VehicleReading.time >= since)
        .scalar_subquery()
    )
    return sites, generators, tractors, keys, func.greatest(last_gen, last_vehicle)


async def _rows(session: AsyncSession, where: list) -> list[TenantRow]:
    sites, generators, tractors, keys, last = _counts()
    query = (
        select(Organisation, Coupon.code, sites, generators, tractors, keys, last)
        .outerjoin(Coupon, Coupon.id == Organisation.coupon_id)
        .where(*where)
        .order_by(Organisation.created_at.desc())
    )
    now = datetime.now(UTC)
    return [
        TenantRow(
            id=org.id,
            name=org.name,
            slug=org.slug,
            kind=tenant_kind(org, now),
            created_at=org.created_at,
            demo_expires_at=org.demo_expires_at,
            converted_at=org.converted_at,
            coupon_code=code,
            sites=s,
            generators=g,
            tractors=t,
            active_keys=k,
            last_reading_at=seen,
        )
        for org, code, s, g, t, k, seen in (await session.execute(query)).all()
    ]


async def _org_or_404(session: AsyncSession, organisation_id: uuid.UUID) -> Organisation:
    org = await session.get(Organisation, organisation_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")
    return org


@router.get("", response_model=list[TenantRow], summary="List tenants")
async def list_tenants(
    kind: TenantKind | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100, description="Name or slug contains."),
    _: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> list[TenantRow]:
    where = []
    if kind is not None:
        where.append(_kind_filter(kind, datetime.now(UTC)))
    if q:
        pattern = f"%{q.strip()}%"
        where.append(or_(Organisation.name.ilike(pattern), Organisation.slug.ilike(pattern)))
    return await _rows(session, where)


@router.get("/{organisation_id}", response_model=TenantDetail, summary="One tenant")
async def get_tenant(
    organisation_id: uuid.UUID,
    _: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> TenantDetail:
    rows = await _rows(session, [Organisation.id == organisation_id])
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found.")

    gen_count = select(func.count()).where(Generator.site_id == Site.id).scalar_subquery()
    sites = (
        await session.execute(
            select(Site, gen_count)
            .where(Site.organisation_id == organisation_id)
            .order_by(Site.name)
        )
    ).all()
    vehicles = (
        await session.execute(
            select(Vehicle).where(Vehicle.organisation_id == organisation_id).order_by(Vehicle.name)
        )
    ).scalars()
    keys = (
        await session.execute(
            select(ApiKey)
            .where(ApiKey.organisation_id == organisation_id)
            .order_by(ApiKey.created_at.desc())
        )
    ).scalars()
    contact = (
        await session.execute(
            select(CouponRedemption.contact_email)
            .where(CouponRedemption.organisation_id == organisation_id)
            .limit(1)
        )
    ).scalar_one_or_none()

    return TenantDetail(
        **rows[0].model_dump(),
        contact_email=contact,
        site_list=[
            TenantSiteOut(
                id=site.id,
                name=site.name,
                profile=site.profile.value,
                generators=count,
                simulation_status=site.simulation_status,
                backfill_error=site.backfill_error,
            )
            for site, count in sites
        ],
        vehicle_list=[
            TenantVehicleOut(
                id=v.id,
                name=v.name,
                serial=v.serial,
                simulation_status=v.simulation_status,
                last_seen_at=v.last_seen_at,
                backfill_error=v.backfill_error,
            )
            for v in vehicles
        ],
        keys=[TenantKeyOut.model_validate(k) for k in keys],
    )


@router.post(
    "",
    response_model=TenantCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer tenant",
)
async def create_tenant(
    payload: TenantCreate,
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> TenantCreated:
    """A real (non-demo) organisation and its first API key, shown once."""
    org = Organisation(
        id=uuid.uuid4(),
        name=payload.name,
        slug=payload.slug or slugify(payload.name)[:60],
        is_demo=False,
    )
    session.add(org)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That slug is already taken."
        ) from None
    key = await _issue(session, org, payload.key_label)
    await audit(session, actor, "tenant.create", "tenant", org.id, {"slug": org.slug})
    rows = await _rows(session, [Organisation.id == org.id])
    return TenantCreated(tenant=rows[0], key=key)


async def _issue(session: AsyncSession, org: Organisation, label: str) -> IssuedTenantKey:
    plaintext, key_hash, prefix = generate_key()
    record = ApiKey(
        id=uuid.uuid4(), organisation_id=org.id, key_hash=key_hash, prefix=prefix, label=label
    )
    session.add(record)
    await session.flush()
    await session.refresh(record)
    return IssuedTenantKey(**TenantKeyOut.model_validate(record).model_dump(), api_key=plaintext)


@router.post(
    "/{organisation_id}/keys",
    response_model=IssuedTenantKey,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a key for a tenant",
)
async def issue_key(
    organisation_id: uuid.UUID,
    payload: KeyCreate,
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> IssuedTenantKey:
    org = await _org_or_404(session, organisation_id)
    key = await _issue(session, org, payload.label)
    await audit(
        session, actor, "key.issue", "tenant", org.id, {"prefix": key.prefix, "label": key.label}
    )
    return key


@router.delete(
    "/{organisation_id}/keys/{key_id}",
    response_model=TenantKeyOut,
    summary="Revoke a tenant's key",
)
async def revoke_key(
    organisation_id: uuid.UUID,
    key_id: uuid.UUID,
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiKey:
    key = (
        await session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.organisation_id == organisation_id)
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found.")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        await audit(session, actor, "key.revoke", "tenant", organisation_id, {"prefix": key.prefix})
    await session.flush()
    return key


def _require_demo(org: Organisation) -> None:
    if not org.is_demo:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This is not a demo tenant."
        )


@router.post("/{organisation_id}/extend", response_model=TenantRow, summary="Extend a demo")
async def extend_demo(
    organisation_id: uuid.UUID,
    payload: ExtendRequest,
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> TenantRow:
    """Adds days from now if the demo has already expired, otherwise from its
    current end. Keys the expiry job revoked are restored if not yet purged."""
    org = await _org_or_404(session, organisation_id)
    _require_demo(org)
    now = datetime.now(UTC)
    base = max(org.demo_expires_at or now, now)
    was_expired = (org.demo_expires_at or now) <= now
    org.demo_expires_at = base + timedelta(days=payload.days)
    if was_expired:
        await _restore_demo_keys(session, org)
    await audit(
        session,
        actor,
        "tenant.extend",
        "tenant",
        org.id,
        {"days": payload.days, "expires_at": org.demo_expires_at.isoformat()},
    )
    await session.flush()
    return (await _rows(session, [Organisation.id == org.id]))[0]


async def _restore_demo_keys(session: AsyncSession, org: Organisation) -> None:
    """Un-revoke keys the expiry job revoked (label "demo"), so the prospect's
    saved key works again. Keys an admin revoked by hand stay revoked."""
    keys = (
        await session.execute(
            select(ApiKey).where(
                ApiKey.organisation_id == org.id,
                ApiKey.label == "demo",
                ApiKey.revoked_at.is_not(None),
            )
        )
    ).scalars()
    for key in keys:
        key.revoked_at = None


@router.post("/{organisation_id}/convert", response_model=TenantRow, summary="Convert a demo")
async def convert_demo(
    organisation_id: uuid.UUID,
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> TenantRow:
    """The prospect signed: keep everything, stop the clock. The expiry job
    never touches a non-demo tenant."""
    org = await _org_or_404(session, organisation_id)
    _require_demo(org)
    if org.demo_expires_at is not None and org.demo_expires_at <= datetime.now(UTC):
        await _restore_demo_keys(session, org)
    org.is_demo = False
    org.demo_expires_at = None
    org.converted_at = datetime.now(UTC)
    await audit(session, actor, "tenant.convert", "tenant", org.id, {"name": org.name})
    await session.flush()
    return (await _rows(session, [Organisation.id == org.id]))[0]


@router.delete(
    "/{organisation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Purge a tenant and all its data",
)
async def purge_tenant(
    organisation_id: uuid.UUID,
    payload: PurgeRequest,
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Irreversible. The exact name must be sent back as confirmation. Real
    tenants can only be purged by an OWNER."""
    org = await _org_or_404(session, organisation_id)
    if payload.confirm_name.strip() != org.name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Type the tenant's exact name to confirm.",
        )
    if not org.is_demo and not actor.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only owners can purge a real tenant."
        )
    await audit(
        session,
        actor,
        "tenant.purge",
        "tenant",
        org.id,
        {"name": org.name, "slug": org.slug, "was_demo": org.is_demo},
    )
    await session.execute(delete(Organisation).where(Organisation.id == org.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
