"""Self-serve demo accounts.

`POST /v1/demo/redeem` is the one unauthenticated write in the API: a valid PoC
code opens a time-limited organisation and returns its key, once. Everything
after that authenticates with the key like any other tenant.

New locations and tractors are accepted with 202: their history is generated
in the background, and `GET /v1/demo/status` reports progress until each one
goes LIVE.
"""

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_organisation
from app.config import Settings, get_settings
from app.db import get_session
from app.models.entities import Coupon, Organisation, SimulationStatus, Site, Vehicle
from app.ratelimit import SlidingWindowLimiter
from app.schemas import (
    DemoEntity,
    DemoLimits,
    DemoStatus,
    DemoUsage,
    LocationCreate,
    OrganisationOut,
    ProvisionedOut,
    RedeemOut,
    RedeemRequest,
    TractorCreate,
)
from app.services.demo_jobs import enqueue_backfill
from app.services.provisioning import (
    CouponRejected,
    LimitReached,
    ProvisioningError,
    create_location,
    create_tractor,
    days_left,
    redeem_coupon,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/demo", tags=["demo"])

_redeem_limiter: SlidingWindowLimiter | None = None


def _limiter(settings: Settings) -> SlidingWindowLimiter:
    global _redeem_limiter
    if _redeem_limiter is None:
        _redeem_limiter = SlidingWindowLimiter(settings.demo_redeem_per_minute, 60.0)
    return _redeem_limiter


def _limits(coupon: Coupon) -> DemoLimits:
    return DemoLimits(
        max_locations=coupon.max_locations,
        max_tractors=coupon.max_tractors,
        max_generators_per_location=coupon.max_generators_per_location,
    )


@router.post(
    "/redeem",
    response_model=RedeemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Open a demo account with a PoC code",
)
async def redeem(
    payload: RedeemRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RedeemOut:
    """Creates the company as a demo organisation and returns its API key.

    The key is shown once. Every failure — unknown, expired, used up or
    switched off — returns the same 400, so the endpoint cannot be used to
    discover which codes exist.
    """
    client_ip = request.client.host if request.client else None
    if not _limiter(settings).allow(client_ip or "unknown"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again in a minute.",
        )
    try:
        organisation, api_key, coupon = await redeem_coupon(session, payload, client_ip)
    except CouponRejected as rejected:
        logger.info("coupon redemption rejected: %s", rejected)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired code."
        ) from None

    assert organisation.demo_expires_at is not None
    return RedeemOut(
        api_key=api_key,
        organisation=OrganisationOut.model_validate(organisation),
        expires_at=organisation.demo_expires_at,
        limits=_limits(coupon),
    )


@router.get("/status", response_model=DemoStatus, summary="Demo account and data readiness")
async def demo_status(
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> DemoStatus:
    """Also answers for a full tenant (is_demo false, no limits), so the
    frontend can call it unconditionally after sign-in."""
    sites = (
        (
            await session.execute(
                select(Site)
                .where(Site.organisation_id == organisation.id)
                .order_by(Site.created_at)
            )
        )
        .scalars()
        .all()
    )
    vehicles = (
        (
            await session.execute(
                select(Vehicle)
                .where(Vehicle.organisation_id == organisation.id)
                .order_by(Vehicle.created_at)
            )
        )
        .scalars()
        .all()
    )

    entities = [
        DemoEntity(
            type="location",
            id=site.id,
            name=site.name,
            simulation_status=site.simulation_status,
            progress=site.backfill_progress,
            error=site.backfill_error,
        )
        for site in sites
    ] + [
        DemoEntity(
            type="tractor",
            id=vehicle.id,
            name=vehicle.name,
            simulation_status=vehicle.simulation_status,
            progress=vehicle.backfill_progress,
            error=vehicle.backfill_error,
        )
        for vehicle in vehicles
    ]

    coupon = await session.get(Coupon, organisation.coupon_id) if organisation.coupon_id else None
    expires_at = organisation.demo_expires_at
    return DemoStatus(
        organisation=OrganisationOut.model_validate(organisation),
        is_demo=organisation.is_demo,
        expires_at=expires_at,
        days_left=days_left(expires_at, datetime.now(UTC)) if expires_at else None,
        limits=_limits(coupon) if coupon else None,
        usage=DemoUsage(locations=len(sites), tractors=len(vehicles)),
        entities=entities,
        generating=any(
            e.simulation_status in (SimulationStatus.PENDING, SimulationStatus.BACKFILLING)
            for e in entities
        ),
    )


def _reject(exc: Exception) -> HTTPException:
    if isinstance(exc, LimitReached):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


@router.post(
    "/locations",
    response_model=ProvisionedOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Add a location to monitor",
)
async def add_location(
    payload: LocationCreate,
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProvisionedOut:
    """A site with its generators, their day tanks (≥ 1000 L) and optional bulk
    storage (≥ 5000 L). Sensor identities are assigned automatically."""
    try:
        site = await create_location(session, organisation, payload)
    except (LimitReached, ProvisioningError) as exc:
        raise _reject(exc) from None
    # Committed here, not by the dependency on the way out: the backfill runs
    # in its own session and must be able to see the rows it is handed.
    await session.commit()
    enqueue_backfill("location", site.id, settings)
    return ProvisionedOut(
        type="location", id=site.id, name=site.name, simulation_status=site.simulation_status
    )


@router.post(
    "/tractors",
    response_model=ProvisionedOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Add a tractor to monitor",
)
async def add_tractor(
    payload: TractorCreate,
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProvisionedOut:
    """A tractor with its onboard tank (150-600 L), a yard and a field within
    25 km of it."""
    try:
        vehicle = await create_tractor(session, organisation, payload)
    except (LimitReached, ProvisioningError) as exc:
        raise _reject(exc) from None
    await session.commit()
    enqueue_backfill("tractor", vehicle.id, settings)
    return ProvisionedOut(
        type="tractor",
        id=vehicle.id,
        name=vehicle.name,
        simulation_status=vehicle.simulation_status,
    )
