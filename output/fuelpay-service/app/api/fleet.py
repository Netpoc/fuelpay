"""Fleet endpoints: sites and generators.

Every query filters on the authenticated organisation. A caller who guesses
another tenant's generator UUID gets a 404, not their data.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.tanks import _latest_levels, _to_state
from app.auth import require_organisation
from app.db import get_session
from app.models.entities import (
    Generator,
    GeneratorStatus,
    Organisation,
    Reading,
    Site,
    Tank,
    TankKind,
)
from app.schemas import GeneratorDetail, GeneratorOut, ReadingOut, SiteOut
from app.simulation.consumption import runtime_hours_remaining

router = APIRouter(prefix="/v1", tags=["fleet"])


@router.get("/sites", response_model=list[SiteOut], summary="List sites")
async def list_sites(
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> list[Site]:
    result = await session.execute(
        select(Site).where(Site.organisation_id == organisation.id).order_by(Site.name)
    )
    return list(result.scalars().all())


@router.get("/generators", response_model=list[GeneratorOut], summary="List generators")
async def list_generators(
    site_id: uuid.UUID | None = Query(default=None, description="Filter to one site."),
    status_filter: GeneratorStatus | None = Query(
        default=None, alias="status", description="Filter by lifecycle status."
    ),
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> list[Generator]:
    query = select(Generator).where(Generator.organisation_id == organisation.id)
    if site_id is not None:
        query = query.where(Generator.site_id == site_id)
    if status_filter is not None:
        query = query.where(Generator.status == status_filter)

    result = await session.execute(query.order_by(Generator.serial))
    return list(result.scalars().all())


@router.get(
    "/generators/{generator_id}",
    response_model=GeneratorDetail,
    summary="Generator detail with its latest reading",
)
async def get_generator(
    generator_id: uuid.UUID,
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> GeneratorDetail:
    row = (
        await session.execute(
            select(Generator, Site)
            .join(Site, Site.id == Generator.site_id)
            .where(
                Generator.id == generator_id,
                Generator.organisation_id == organisation.id,
            )
        )
    ).first()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generator not found.")

    generator, site = row

    latest = (
        await session.execute(
            select(Reading)
            .where(Reading.generator_id == generator_id)
            .order_by(Reading.time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    hours_to_empty = None
    if latest is not None and latest.engine_running:
        hours_to_empty = runtime_hours_remaining(
            latest.fuel_level_l,
            generator.kva_rating,
            generator.power_factor,
            latest.load_pct / 100.0,
        )

    # The instrumented day tank, whose sensor may be reporting or not. Distinct
    # from `latest.fuel_level_l`, which is the same tank seen through the
    # generator's own telemetry row and therefore always present.
    day_tank = (
        await session.execute(
            select(Tank).where(
                Tank.generator_id == generator_id,
                Tank.kind == TankKind.DAY,
            )
        )
    ).scalar_one_or_none()

    day_tank_state = None
    if day_tank is not None:
        now = datetime.now(UTC)
        levels = await _latest_levels(session, organisation.id, [day_tank.id])
        day_tank_state = _to_state(day_tank, levels.get(day_tank.id), now)

    # Built from the joined row rather than `model_validate(generator)`: the
    # latter would resolve Generator.site as a lazy load, which raises under
    # asyncio. The site is already in hand, so hand it over directly.
    return GeneratorDetail(
        **GeneratorOut.model_validate(generator).model_dump(),
        site=SiteOut.model_validate(site),
        day_tank=day_tank_state,
        latest=ReadingOut.model_validate(latest) if latest is not None else None,
        hours_to_empty=round(hours_to_empty, 2) if hours_to_empty is not None else None,
    )
