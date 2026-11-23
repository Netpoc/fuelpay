"""Key management and simulation control for the authenticated organisation.

Issuing requires an existing valid key, which is what makes the bootstrap key
in configuration meaningful: it is the root of trust a tenant uses once, to
mint the keys it will actually deploy, before revoking nothing and rotating at
its own pace.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_key, require_full_tenant, require_organisation
from app.config import Settings, get_settings
from app.db import get_session
from app.models.entities import (
    ApiKey,
    Generator,
    Organisation,
    SimulationState,
    Tank,
    TankKind,
    TankSimulationState,
)
from app.schemas import (
    ApiKeyOut,
    DrainRequest,
    GeneratorLag,
    IssuedKey,
    IssueKeyRequest,
    LevelRequest,
    RefillRequest,
    SimulateOut,
    SimulationStatus,
    TickOut,
)
from app.services.simulate import (
    GeneratorNotFound,
    SimulateResult,
    force_refill,
    inject_drain,
    set_level,
)
from app.services.ticker import run_tick

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/api-keys", response_model=list[ApiKeyOut], summary="List this tenant's keys")
async def list_api_keys(
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKey]:
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.organisation_id == organisation.id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars().all())


@router.post(
    "/api-keys",
    response_model=IssuedKey,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a new key",
)
async def issue_api_key(
    payload: IssueKeyRequest,
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> IssuedKey:
    plaintext, key_hash, prefix = generate_key()

    record = ApiKey(
        id=uuid.uuid4(),
        organisation_id=organisation.id,
        key_hash=key_hash,
        prefix=prefix,
        label=payload.label,
    )
    session.add(record)
    await session.flush()
    # created_at is a server default, so it is unset on the in-memory object
    # until the INSERT's value is read back.
    await session.refresh(record)

    return IssuedKey(**ApiKeyOut.model_validate(record).model_dump(), api_key=plaintext)


@router.delete(
    "/api-keys/{key_id}",
    response_model=ApiKeyOut,
    summary="Revoke a key",
)
async def revoke_api_key(
    key_id: uuid.UUID,
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
) -> ApiKey:
    record = (
        await session.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.organisation_id == organisation.id,
            )
        )
    ).scalar_one_or_none()

    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")

    # Revoking is idempotent, but the original revocation time is preserved:
    # it may matter later which request a key stopped working for.
    if record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
        await session.flush()

    return record


@router.post("/tick", response_model=TickOut, summary="Run one simulation tick now")
async def tick_now(
    organisation: Organisation = Depends(require_full_tenant),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> TickOut:
    """Advance the simulation to the present without waiting for the scheduler.

    Useful for demos and tests, where waiting out `sim_tick_seconds` for the
    next reading is the difference between a live-looking service and a
    seemingly broken one.

    The tick is fleet-wide, not tenant-scoped: the simulated clock belongs to
    the service, and letting one tenant advance only its own generators would
    leave the fleet at inconsistent points in time. Authentication here is
    about who may poke the simulator, not about what gets advanced.

    Returns `skipped_locked: true` if the scheduler happened to be mid-tick —
    that is the lock working, not an error, and the data is already current.
    """
    now = datetime.now(UTC)
    report = await run_tick(session, settings, now)

    return TickOut(
        generators=report.generators,
        readings=report.readings,
        events=report.events,
        skipped_locked=report.skipped_locked,
        still_catching_up=report.still_catching_up,
        ticked_at=now,
    )


def _simulate_out(result: SimulateResult) -> SimulateOut:
    return SimulateOut(
        generator_id=result.generator_id,
        steps=result.steps,
        readings=result.readings,
        events=result.event_types,
        fuel_level_l=result.fuel_level_l,
        fuel_level_pct=result.fuel_level_pct,
        staged_from_l=result.staged_from_l,
        simulated_from=result.simulated_from,
        simulated_to=result.simulated_to,
    )


@router.post(
    "/simulate/drain",
    response_model=SimulateOut,
    summary="Start a fuel siphon on one generator",
)
async def simulate_drain(
    payload: DrainRequest,
    organisation: Organisation = Depends(require_full_tenant),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SimulateOut:
    """Stage a theft and run it far enough to be visible.

    Left to itself the simulator sipohns roughly once per generator per 67
    days, at night, with the engine off. This is how you show someone what that
    looks like without waiting.

    The siphon drains over several steps at the pump's rate, so it emits a
    *series* of SUSPECTED_DRAIN events exactly as an unprompted theft does —
    the rows are indistinguishable from naturally occurring ones.
    """
    try:
        result = await inject_drain(
            session,
            settings,
            payload.generator_id,
            organisation.id,
            volume_l=payload.volume_l,
            steps=payload.steps,
        )
    except GeneratorNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Generator not found."
        ) from None

    return _simulate_out(result)


@router.post(
    "/simulate/level",
    response_model=SimulateOut,
    summary="Set a tank level, then step",
)
async def simulate_level(
    payload: LevelRequest,
    organisation: Organisation = Depends(require_full_tenant),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SimulateOut:
    """Move a tank to a chosen level.

    The primitive for staging level-driven incidents: park a tank just above
    its reorder threshold and the next steps emit LOW_FUEL as consumption
    carries it across, with no special-casing anywhere.
    """
    if (payload.level_l is None) == (payload.level_pct is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide exactly one of level_l or level_pct.",
        )

    try:
        result = await set_level(
            session,
            settings,
            payload.generator_id,
            organisation.id,
            level_l=payload.level_l,
            level_pct=payload.level_pct,
            steps=payload.steps,
        )
    except GeneratorNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Generator not found."
        ) from None

    return _simulate_out(result)


@router.post(
    "/simulate/refill",
    response_model=SimulateOut,
    summary="Trigger a refill on one generator",
)
async def simulate_refill(
    payload: RefillRequest,
    organisation: Organisation = Depends(require_full_tenant),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SimulateOut:
    """Dispatch a tanker to one generator now.

    The volume delivered and the 90-100% fill target come from the engine, so
    the resulting REFILL is consistent with every other refill in the data.

    A tank already below its reorder threshold is filled with no level change
    at all. A fuller one is first lowered to just under the threshold, since a
    near-full tank would not receive a delivery; the response reports that as
    `staged_from_l` so the jump is not mistaken for a drain.
    """
    try:
        result = await force_refill(
            session,
            settings,
            payload.generator_id,
            organisation.id,
            steps=payload.steps,
        )
    except GeneratorNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Generator not found."
        ) from None

    return _simulate_out(result)


@router.get("/simulation", response_model=SimulationStatus, summary="Simulated-clock lag")
async def simulation_status(
    organisation: Organisation = Depends(require_organisation),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SimulationStatus:
    """How far behind wall-clock each generator's simulated clock is running.

    A healthy fleet sits below one tick interval. Sustained growth means ticks
    are failing or taking longer than the interval they run on.
    """
    rows = (
        await session.execute(
            select(SimulationState, Generator.name, TankSimulationState.level_l)
            .join(Generator, Generator.id == SimulationState.generator_id)
            # Fuel moved to the tank in 0002; the day tank's level is the one
            # this unit burns from.
            .outerjoin(
                Tank, (Tank.generator_id == Generator.id) & (Tank.kind == TankKind.DAY)
            )
            .outerjoin(TankSimulationState, TankSimulationState.tank_id == Tank.id)
            .where(Generator.organisation_id == organisation.id)
            .order_by(SimulationState.simulated_at)
        )
    ).all()

    now = datetime.now(UTC)
    lags = [
        GeneratorLag(
            generator_id=state.generator_id,
            name=name,
            simulated_at=state.simulated_at,
            lag_seconds=round((now - state.simulated_at).total_seconds(), 1),
            fuel_level_l=round(level_l or 0.0, 2),
            engine_running=state.engine_running,
        )
        for state, name, level_l in rows
    ]

    return SimulationStatus(
        enabled=settings.sim_enabled,
        tick_seconds=settings.sim_tick_seconds,
        minutes_per_tick=settings.sim_minutes_per_tick,
        tracked_generators=len(lags),
        max_lag_seconds=max((lag.lag_seconds for lag in lags), default=None),
        generators=lags,
        as_of=now,
    )
