"""Self-serve creation of demo tenants and the things they monitor.

Three steps, matching the signup flow:

1. `redeem_coupon` — a PoC code opens a time-limited demo organisation and
   returns its API key, once.
2. `create_location` — a site with generators, their day tanks and optional
   bulk storage, as the prospect describes it.
3. `create_tractor` — a machine with its onboard tank, a yard and a field.

Each entity is created PENDING. Its history is generated afterwards by
`app.services.demo_jobs`, and only then does the live ticker pick it up.

The rules the seeded fleet follows are enforced here too: tanks ≥ 1000 L,
bulk ≥ 5000 L, generators inside the 25-100 kVA band, and every tank carries a
sensor identity — generated, since a prospect has no hardware to name.

The validation helpers are pure so they can be tested without a database.
"""

import hashlib
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_key
from app.models.entities import (
    ApiKey,
    Coupon,
    CouponRedemption,
    Generator,
    GeneratorStatus,
    Organisation,
    SimulationStatus,
    Site,
    Tank,
    TankKind,
    Vehicle,
    VehicleKind,
    VehicleOperation,
)
from app.schemas import LocationCreate, RedeemRequest, TractorCreate
from app.services.fleet import (
    BULK_SENSOR_MODEL,
    DAY_SENSOR_MODEL,
    KVA_OPTIONS,
    MIN_TANK_CAPACITY_L,
)
from app.simulation.field import haversine_m

# Bulk storage floor: the external tank tier starts here in the target market.
MIN_BULK_CAPACITY_L = 5000.0
# A tractor works within reach of its yard; further than this is a different
# farm, and the transit leg would dominate the day.
MAX_FIELD_DISTANCE_M = 25_000.0

# Technoton's capacitive probe is the common fit on agricultural machinery.
VEHICLE_SENSOR_MODEL = "Technoton DUT-E"

# Crockford base32 minus the look-alikes, so a code read over the phone or off
# a slide survives transcription.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"


class CouponRejected(Exception):
    """The code cannot be redeemed. The reason is for logs, never the client."""


class LimitReached(Exception):
    """The demo's coupon does not allow another entity of this kind."""


class ProvisioningError(ValueError):
    """The request is well-formed but describes something FuelPay won't model."""


# --- pure helpers ---------------------------------------------------------


def normalise_code(code: str) -> str:
    return code.strip().upper()


def generate_coupon_code(groups: int = 2, size: int = 4) -> str:
    """e.g. `K7PX-M3QD`."""
    return "-".join(
        "".join(secrets.choice(_CODE_ALPHABET) for _ in range(size)) for _ in range(groups)
    )


def coupon_rejection(coupon: Coupon | None, now: datetime) -> str | None:
    """Why this coupon cannot be redeemed now, or None if it can."""
    if coupon is None:
        return "unknown code"
    if not coupon.is_active:
        return "inactive"
    if coupon.expires_at is not None and coupon.expires_at <= now:
        return "expired"
    if coupon.redemptions_count >= coupon.max_redemptions:
        return "exhausted"
    return None


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "company"


def demo_slug(company_name: str) -> str:
    """Never collides with the seeded `demo` org: always prefixed and suffixed."""
    return f"demo-{slugify(company_name)[:40]}-{secrets.token_hex(3)}"


def hash_ip(address: str | None) -> str | None:
    return hashlib.sha256(address.encode()).hexdigest() if address else None


def days_left(expires_at: datetime, now: datetime) -> int:
    """Whole days remaining, rounded up, so the last day reads 1 rather than 0."""
    seconds = (expires_at - now).total_seconds()
    if seconds <= 0:
        return 0
    return int(-(-seconds // 86_400))


def validate_location(payload: LocationCreate, max_generators: int) -> None:
    """Domain checks beyond what the schema's field bounds express."""
    if len(payload.generators) > max_generators:
        raise ProvisioningError(f"This demo allows up to {max_generators} generators per location.")
    for generator in payload.generators:
        if generator.kva_rating not in KVA_OPTIONS:
            options = ", ".join(f"{k:g}" for k in KVA_OPTIONS)
            raise ProvisioningError(f"kVA rating must be one of {options}.")
        if generator.day_tank_capacity_l < MIN_TANK_CAPACITY_L:
            raise ProvisioningError("Day tanks start at 1000 L.")
    for tank in payload.bulk_tanks:
        if tank.capacity_l < MIN_BULK_CAPACITY_L:
            raise ProvisioningError("Bulk tanks start at 5000 L.")
    names = [g.name.strip().lower() for g in payload.generators]
    if len(set(names)) != len(names):
        raise ProvisioningError("Generator names must be unique within a location.")


def validate_tractor(payload: TractorCreate) -> None:
    distance = haversine_m(
        payload.yard.latitude,
        payload.yard.longitude,
        payload.field.latitude,
        payload.field.longitude,
    )
    if distance > MAX_FIELD_DISTANCE_M:
        raise ProvisioningError("The field must be within 25 km of the yard.")


def _serial_suffix() -> str:
    return secrets.token_hex(3).upper()


# --- database steps -------------------------------------------------------


async def redeem_coupon(
    session: AsyncSession,
    payload: RedeemRequest,
    client_ip: str | None,
    now: datetime | None = None,
) -> tuple[Organisation, str, Coupon]:
    """Open a demo organisation. Returns (organisation, plaintext key, coupon).

    The coupon row is locked for the transaction, so concurrent redemptions of
    a nearly-exhausted code serialise here and exactly `max_redemptions` win.
    Does not commit.
    """
    now = now or datetime.now(UTC)
    coupon = (
        await session.execute(
            select(Coupon).where(Coupon.code == normalise_code(payload.code)).with_for_update()
        )
    ).scalar_one_or_none()

    reason = coupon_rejection(coupon, now)
    if reason is not None:
        raise CouponRejected(reason)
    assert coupon is not None

    coupon.redemptions_count += 1

    organisation = Organisation(
        id=uuid.uuid4(),
        name=payload.company_name,
        slug=demo_slug(payload.company_name),
        is_demo=True,
        demo_expires_at=now + timedelta(days=coupon.demo_duration_days),
        coupon_id=coupon.id,
    )
    session.add(organisation)
    # The key and redemption reference it, and no ORM relationship tells the
    # unit of work to insert it first.
    await session.flush()

    plaintext, key_hash, prefix = generate_key()
    session.add(
        ApiKey(
            id=uuid.uuid4(),
            organisation_id=organisation.id,
            key_hash=key_hash,
            prefix=prefix,
            label="demo",
        )
    )
    session.add(
        CouponRedemption(
            id=uuid.uuid4(),
            coupon_id=coupon.id,
            organisation_id=organisation.id,
            company_name=payload.company_name,
            contact_email=payload.contact_email,
            ip_hash=hash_ip(client_ip),
        )
    )
    await session.flush()
    return organisation, plaintext, coupon


async def demo_coupon(session: AsyncSession, organisation: Organisation) -> Coupon:
    """The coupon that sets this demo's limits. Locks the organisation row so
    concurrent creates count each other before inserting."""
    if not organisation.is_demo or organisation.coupon_id is None:
        raise LimitReached("Only demo accounts can add entities this way.")

    await session.execute(
        select(Organisation.id).where(Organisation.id == organisation.id).with_for_update()
    )
    coupon = await session.get(Coupon, organisation.coupon_id)
    if coupon is None:
        raise LimitReached("This demo's coupon no longer exists.")
    return coupon


async def count_entities(session: AsyncSession, organisation_id: uuid.UUID) -> tuple[int, int]:
    """(locations, tractors) the organisation currently has."""
    sites = (
        await session.execute(
            select(func.count()).select_from(Site).where(Site.organisation_id == organisation_id)
        )
    ).scalar_one()
    vehicles = (
        await session.execute(
            select(func.count())
            .select_from(Vehicle)
            .where(Vehicle.organisation_id == organisation_id)
        )
    ).scalar_one()
    return int(sites), int(vehicles)


async def create_location(
    session: AsyncSession, organisation: Organisation, payload: LocationCreate
) -> Site:
    """Create a site with its generators, day tanks and bulk storage. PENDING.

    Always a new site: adding a generator to a site that already has history
    would leave its tanks at inconsistent points in simulated time.
    """
    coupon = await demo_coupon(session, organisation)
    locations, _ = await count_entities(session, organisation.id)
    if locations >= coupon.max_locations:
        raise LimitReached(f"This demo allows {coupon.max_locations} location(s).")
    validate_location(payload, coupon.max_generators_per_location)

    clash = (
        await session.execute(
            select(Site.id).where(
                Site.organisation_id == organisation.id, Site.name == payload.name
            )
        )
    ).first()
    if clash is not None:
        raise ProvisioningError("You already have a location with that name.")

    now = datetime.now(UTC)
    site = Site(
        id=uuid.uuid4(),
        organisation_id=organisation.id,
        name=payload.name,
        profile=payload.profile,
        latitude=payload.latitude,
        longitude=payload.longitude,
        address=payload.address,
        simulation_status=SimulationStatus.PENDING,
        backfill_progress=0.0,
    )
    session.add(site)

    suffix = _serial_suffix()
    tanks: list[Tank] = []
    for number, bulk in enumerate(payload.bulk_tanks, start=1):
        tanks.append(
            Tank(
                id=uuid.uuid4(),
                organisation_id=organisation.id,
                site_id=site.id,
                generator_id=None,
                name=bulk.name or f"{payload.name} Bulk {number}",
                kind=TankKind.BULK,
                capacity_l=bulk.capacity_l,
                reorder_threshold_pct=bulk.reorder_threshold_pct,
                sensor_model=BULK_SENSOR_MODEL,
                sensor_serial=f"ESC-B-{suffix}-{number:02d}",
                calibrated_at=now,
            )
        )

    generators: list[Generator] = []
    for number, spec in enumerate(payload.generators, start=1):
        generator = Generator(
            id=uuid.uuid4(),
            organisation_id=organisation.id,
            site_id=site.id,
            name=spec.name,
            serial=f"FP-{int(spec.kva_rating):03d}-{suffix}-{number:02d}",
            kva_rating=spec.kva_rating,
            power_factor=0.8,
            tank_capacity_l=spec.day_tank_capacity_l,
            reorder_threshold_pct=spec.reorder_threshold_pct,
            status=GeneratorStatus.ACTIVE,
            commissioned_at=now,
        )
        generators.append(generator)
        tanks.append(
            Tank(
                id=uuid.uuid4(),
                organisation_id=organisation.id,
                site_id=site.id,
                generator_id=generator.id,
                name=f"{spec.name} Day Tank",
                kind=TankKind.DAY,
                capacity_l=spec.day_tank_capacity_l,
                reorder_threshold_pct=spec.reorder_threshold_pct,
                sensor_model=DAY_SENSOR_MODEL,
                sensor_serial=f"ESC-D-{suffix}-{number:02d}",
                calibrated_at=now,
            )
        )

    # Tanks reference generators, so both must exist before the FK is checked.
    session.add_all(generators)
    await session.flush()
    session.add_all(tanks)
    await session.flush()
    return site


async def create_tractor(
    session: AsyncSession, organisation: Organisation, payload: TractorCreate
) -> Vehicle:
    """Create a tractor with its onboard tank, yard and field. PENDING."""
    coupon = await demo_coupon(session, organisation)
    _, tractors = await count_entities(session, organisation.id)
    if tractors >= coupon.max_tractors:
        raise LimitReached(f"This demo allows {coupon.max_tractors} tractor(s).")
    validate_tractor(payload)

    suffix = _serial_suffix()
    vehicle = Vehicle(
        id=uuid.uuid4(),
        organisation_id=organisation.id,
        name=payload.name,
        kind=VehicleKind.TRACTOR,
        make_model=payload.make_model,
        serial=f"TR-{suffix}",
        engine_kw=payload.engine_kw,
        tank_capacity_l=payload.tank_capacity_l,
        fuel_sensor_model=VEHICLE_SENSOR_MODEL,
        fuel_sensor_serial=f"DUT-{suffix}",
        calibrated_at=datetime.now(UTC),
        yard_latitude=payload.yard.latitude,
        yard_longitude=payload.yard.longitude,
        field_latitude=payload.field.latitude,
        field_longitude=payload.field.longitude,
        field_width_m=payload.field.width_m,
        field_length_m=payload.field.length_m,
        field_heading_deg=payload.field.heading_deg,
        primary_operation=VehicleOperation(payload.primary_operation),
        working_hours_start=payload.working_hours_start,
        working_hours_end=payload.working_hours_end,
        simulation_status=SimulationStatus.PENDING,
        backfill_progress=0.0,
    )
    session.add(vehicle)
    await session.flush()
    return vehicle
