"""Row writers shared by the backfill and the live ticker.

These live apart from either caller because both need them and neither owns
them: history and live data are written by exactly the same statements, so a
row's provenance is invisible downstream — which is the point.

Simulation state is stored in two places because fuel is two-tier. What belongs
to the engine (where it is in time, whether it is running) stays in
`simulation_state`; fuel levels live in `tank_simulation_state`, since a bulk
tank shared by several generators cannot hang its level off any one of them.
"""

import uuid
from dataclasses import asdict

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Event,
    Reading,
    SimulationState,
    Tank,
    TankReading,
    TankSimulationState,
    Vehicle,
    VehicleReading,
    VehicleSimulationState,
)
from app.simulation.engine import (
    EventSample,
    ReadingSample,
    SiteSpec,
    SiteState,
    TankReadingSample,
    TankState,
)
from app.simulation.vehicle import VehicleReadingSample, VehicleState

# Rows per executemany round-trip. Large enough to amortise the round-trip,
# small enough that a month of fleet history never sits in one parameter list.
INSERT_BATCH_SIZE = 2_000


async def insert_readings(session: AsyncSession, samples: list[ReadingSample]) -> int:
    """Bulk-insert readings, skipping any (generator, time) already present.

    ON CONFLICT DO NOTHING makes re-running over an overlapping window safe
    instead of a primary key violation.
    """
    written = 0
    for start in range(0, len(samples), INSERT_BATCH_SIZE):
        batch = samples[start : start + INSERT_BATCH_SIZE]
        statement = pg_insert(Reading).values([asdict(sample) for sample in batch])
        statement = statement.on_conflict_do_nothing(index_elements=["generator_id", "time"])
        result = await session.execute(statement)
        written += result.rowcount or 0
    return written


async def insert_tank_readings(session: AsyncSession, samples: list[TankReadingSample]) -> int:
    """Bulk-insert tank levels, skipping any (tank, time) already present.

    Sparser than `readings` by design: a tank whose sensor has lost signal
    contributes no rows for that period, and that absence is the signal.
    """
    written = 0
    for start in range(0, len(samples), INSERT_BATCH_SIZE):
        batch = samples[start : start + INSERT_BATCH_SIZE]
        statement = pg_insert(TankReading).values([asdict(sample) for sample in batch])
        statement = statement.on_conflict_do_nothing(index_elements=["tank_id", "time"])
        result = await session.execute(statement)
        written += result.rowcount or 0
    return written


async def touch_tank_last_seen(session: AsyncSession, samples: list[TankReadingSample]) -> None:
    """Advance `tanks.last_seen_at` to the newest reading each tank produced.

    Denormalised so a fleet listing can show connectivity without a correlated
    MAX(time) per tank. Only moves forward, so replaying an older window cannot
    make a live sensor look stale.
    """
    newest: dict[uuid.UUID, object] = {}
    for sample in samples:
        current = newest.get(sample.tank_id)
        if current is None or sample.time > current:  # type: ignore[operator]
            newest[sample.tank_id] = sample.time

    for tank_id, seen_at in newest.items():
        await session.execute(
            update(Tank)
            .where(
                Tank.id == tank_id,
                (Tank.last_seen_at.is_(None)) | (Tank.last_seen_at < seen_at),
            )
            .values(last_seen_at=seen_at)
        )


async def insert_events(session: AsyncSession, samples: list[EventSample]) -> int:
    """Bulk-insert events.

    Unlike readings these have no natural key to conflict on, so callers must
    not replay a window they have already written.
    """
    written = 0
    for start in range(0, len(samples), INSERT_BATCH_SIZE):
        batch = samples[start : start + INSERT_BATCH_SIZE]
        await session.execute(
            pg_insert(Event).values([{"id": uuid.uuid4(), **asdict(sample)} for sample in batch])
        )
        written += len(batch)
    return written


async def save_site_state(session: AsyncSession, spec: SiteSpec, state: SiteState) -> None:
    """Upsert the resume cursor for one site: its engines and all its tanks."""
    for generator in spec.generators:
        values = {
            "generator_id": generator.id,
            "simulated_at": state.simulated_at,
            "engine_running": state.engine_running.get(generator.id, False),
            "tick_index": state.tick_index,
        }
        statement = pg_insert(SimulationState).values(**values)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["generator_id"],
                set_={key: value for key, value in values.items() if key != "generator_id"},
            )
        )

    for tank_id, tank_state in state.tanks.items():
        values = {
            "tank_id": tank_id,
            "level_l": tank_state.level_l,
            "pending_drain_l": tank_state.pending_drain_l,
            "signal_out_ticks": tank_state.signal_out_ticks,
            "level_at_signal_loss_l": tank_state.level_at_signal_loss_l,
            "accounted_outflow_l": tank_state.accounted_outflow_l,
        }
        statement = pg_insert(TankSimulationState).values(**values)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["tank_id"],
                set_={key: value for key, value in values.items() if key != "tank_id"},
            )
        )


async def load_generator_cursors(session: AsyncSession) -> dict[uuid.UUID, SimulationState]:
    """Read every persisted engine cursor, keyed by generator."""
    rows = (await session.execute(select(SimulationState))).scalars().all()
    return {row.generator_id: row for row in rows}


async def load_tank_states(session: AsyncSession) -> dict[uuid.UUID, TankState]:
    """Read every persisted tank level, keyed by tank."""
    rows = (await session.execute(select(TankSimulationState))).scalars().all()
    return {
        row.tank_id: TankState(
            level_l=row.level_l,
            pending_drain_l=row.pending_drain_l,
            signal_out_ticks=row.signal_out_ticks,
            level_at_signal_loss_l=row.level_at_signal_loss_l,
            accounted_outflow_l=row.accounted_outflow_l,
        )
        for row in rows
    }


async def insert_vehicle_readings(
    session: AsyncSession, samples: list[VehicleReadingSample]
) -> int:
    """Bulk-insert machine telemetry, skipping any (vehicle, time) already present,
    and advance each vehicle's `last_seen_at`."""
    written = 0
    newest: dict[uuid.UUID, object] = {}
    for start in range(0, len(samples), INSERT_BATCH_SIZE):
        batch = samples[start : start + INSERT_BATCH_SIZE]
        statement = pg_insert(VehicleReading).values([asdict(sample) for sample in batch])
        statement = statement.on_conflict_do_nothing(index_elements=["vehicle_id", "time"])
        result = await session.execute(statement)
        written += result.rowcount or 0
        for sample in batch:
            newest[sample.vehicle_id] = sample.time

    for vehicle_id, seen_at in newest.items():
        await session.execute(
            update(Vehicle)
            .where(
                Vehicle.id == vehicle_id,
                (Vehicle.last_seen_at.is_(None)) | (Vehicle.last_seen_at < seen_at),
            )
            .values(last_seen_at=seen_at)
        )
    return written


async def save_vehicle_state(
    session: AsyncSession, vehicle_id: uuid.UUID, state: VehicleState
) -> None:
    values = {
        "vehicle_id": vehicle_id,
        "simulated_at": state.simulated_at,
        "tick_index": state.tick_index,
        "fuel_level_l": state.fuel_level_l,
        "engine_hours": state.engine_hours,
        "memory": state.memory,
    }
    statement = pg_insert(VehicleSimulationState).values(**values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["vehicle_id"],
            set_={key: value for key, value in values.items() if key != "vehicle_id"},
        )
    )


async def load_vehicle_states(session: AsyncSession) -> dict[uuid.UUID, VehicleState]:
    rows = (await session.execute(select(VehicleSimulationState))).scalars().all()
    return {
        row.vehicle_id: VehicleState(
            simulated_at=row.simulated_at,
            tick_index=row.tick_index,
            fuel_level_l=row.fuel_level_l,
            engine_hours=row.engine_hours,
            memory=dict(row.memory),
        )
        for row in rows
    }
