"""PoC coupons: create, change, and see who redeemed them."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin_schemas import CouponWithUsage
from app.db import get_session
from app.models.entities import Coupon, CouponRedemption, Organisation
from app.schemas import (
    CouponCreate,
    CouponDetail,
    CouponOut,
    CouponRedemptionOut,
    CouponUpdate,
)
from app.services.admin_auth import AdminActor, audit, require_platform_admin
from app.services.provisioning import generate_coupon_code, normalise_code

router = APIRouter(prefix="/coupons")


@router.post(
    "",
    response_model=CouponOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a PoC coupon",
)
async def create_coupon(
    payload: CouponCreate,
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> Coupon:
    code = normalise_code(payload.code) if payload.code else generate_coupon_code()
    coupon = Coupon(
        id=uuid.uuid4(),
        code=code,
        **payload.model_dump(exclude={"code"}),
    )
    session.add(coupon)
    try:
        await session.flush()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="That code already exists."
        ) from None
    await session.refresh(coupon)
    await audit(session, actor, "coupon.create", "coupon", coupon.id, {"code": coupon.code})
    return coupon


@router.get("", response_model=list[CouponWithUsage], summary="List coupons")
async def list_coupons(
    _: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> list[CouponWithUsage]:
    """With how many demos each coupon opened went on to become customers."""
    converted = (
        select(func.count())
        .where(Organisation.coupon_id == Coupon.id, Organisation.converted_at.is_not(None))
        .scalar_subquery()
    )
    rows = (
        await session.execute(select(Coupon, converted).order_by(Coupon.created_at.desc()))
    ).all()
    return [
        CouponWithUsage(**CouponOut.model_validate(c).model_dump(), conversions=n) for c, n in rows
    ]


async def _coupon_or_404(session: AsyncSession, coupon_id: uuid.UUID) -> Coupon:
    coupon = await session.get(Coupon, coupon_id)
    if coupon is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coupon not found.")
    return coupon


@router.get("/{coupon_id}", response_model=CouponDetail, summary="One coupon")
async def get_coupon(
    coupon_id: uuid.UUID,
    _: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> CouponDetail:
    coupon = await _coupon_or_404(session, coupon_id)
    redemptions = (
        await session.execute(
            select(CouponRedemption)
            .where(CouponRedemption.coupon_id == coupon.id)
            .order_by(CouponRedemption.redeemed_at.desc())
        )
    ).scalars()
    return CouponDetail(
        **CouponOut.model_validate(coupon).model_dump(),
        redemptions=[CouponRedemptionOut.model_validate(r) for r in redemptions],
    )


@router.patch("/{coupon_id}", response_model=CouponOut, summary="Change a coupon")
async def update_coupon(
    coupon_id: uuid.UUID,
    payload: CouponUpdate,
    actor: AdminActor = Depends(require_platform_admin),
    session: AsyncSession = Depends(get_session),
) -> Coupon:
    """Deactivate, extend or re-limit a code. Already-open demos keep the
    expiry they were given, but entity limits apply to them from now on."""
    coupon = await _coupon_or_404(session, coupon_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("max_redemptions", coupon.max_redemptions) < coupon.redemptions_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="max_redemptions cannot drop below redemptions already made.",
        )
    for key, value in changes.items():
        setattr(coupon, key, value)
    await session.flush()
    await audit(
        session,
        actor,
        "coupon.update",
        "coupon",
        coupon.id,
        {"code": coupon.code, "changes": payload.model_dump(exclude_unset=True, mode="json")},
    )
    return coupon
