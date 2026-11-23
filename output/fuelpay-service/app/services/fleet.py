"""Demo fleet construction.

Builds a plausible Nigerian off-grid fleet: telecom towers that never stop,
offices that follow business hours, and residential estates that fill the gaps
around grid outages. Sites are real cities so map views look sensible rather
than scattering markers into the Gulf of Guinea.

Deterministic given a seed, so two people running `docker compose up` end up
looking at the same fleet.
"""

import random
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_key
from app.config import Settings
from app.models.entities import (
    ApiKey,
    Generator,
    GeneratorStatus,
    Organisation,
    Site,
    SiteProfile,
    Tank,
    TankKind,
)
from app.simulation.profiles import default_bulk_capacity_l, default_tank_capacity_l

# FuelPay's market floor. Smaller tanks exist in the field but are not what the
# platform is sold into, and instrumenting one is rarely worth the hardware.
MIN_TANK_CAPACITY_L = 1000.0

# (display name, latitude, longitude, profile, street address)
LOCATIONS: tuple[tuple[str, float, float, SiteProfile, str], ...] = (
    ("Ikeja Branch", 6.6018, 3.3515, SiteProfile.BANK_BRANCH, "Obafemi Awolowo Way, Ikeja"),
    ("Victoria Island HQ", 6.4281, 3.4219, SiteProfile.BANK_BRANCH, "Adeola Odeku St, Lagos"),
    ("Wuse II Tower", 9.0765, 7.4692, SiteProfile.TELECOM_TOWER, "Aminu Kano Cres, Wuse II, Abuja"),
    ("Port Harcourt Branch", 4.8156, 7.0498, SiteProfile.BANK_BRANCH, "Aba Road, Port Harcourt"),
    ("Kano Relay Station", 12.0022, 8.5920, SiteProfile.TELECOM_TOWER, "Zaria Road, Kano"),
    ("Ibadan Branch", 7.3775, 3.9470, SiteProfile.BANK_BRANCH, "Ring Road, Ibadan"),
    ("Enugu Residences", 6.4584, 7.5464, SiteProfile.RESIDENTIAL, "Independence Layout, Enugu"),
    ("Kaduna Regional Office", 10.5222, 7.4383, SiteProfile.OFFICE, "Ahmadu Bello Way, Kaduna"),
)

# Standard genset ratings inside the 25-100 kVA band the brief covers.
KVA_OPTIONS: tuple[float, ...] = (25.0, 30.0, 40.0, 50.0, 60.0, 75.0, 100.0)

# Telecom sites run hardest, so they get the bigger units; residential estates
# only cover evening peaks and are sized down. Branches sit at the top of the
# band: the whole hall plus its cooling runs off the set during an outage.
KVA_BY_PROFILE: dict[SiteProfile, tuple[float, ...]] = {
    SiteProfile.TELECOM_TOWER: (40.0, 50.0, 60.0, 75.0, 100.0),
    SiteProfile.OFFICE: (50.0, 60.0, 75.0, 100.0),
    SiteProfile.RESIDENTIAL: (25.0, 30.0, 40.0),
    SiteProfile.BANK_BRANCH: (60.0, 75.0, 100.0),
}

# How many bulk tanks a site installs, by profile. Branches carry the larger
# reserve and split it, which is both how they are actually plumbed and what
# exercises the multi-source transfer path.
BULK_TANK_COUNT: dict[SiteProfile, int] = {
    SiteProfile.TELECOM_TOWER: 1,
    SiteProfile.OFFICE: 1,
    SiteProfile.RESIDENTIAL: 1,
    SiteProfile.BANK_BRANCH: 2,
}

# Escort capacitive probes are the common aftermarket fit on Nigerian sites;
# the OEM float gauge is what ships inside a genset's own tank.
BULK_SENSOR_MODEL = "Escort TD-BLE"
DAY_SENSOR_MODEL = "Escort TD-150"


async def organisation_by_slug(session: AsyncSession, slug: str) -> Organisation | None:
    result = await session.execute(select(Organisation).where(Organisation.slug == slug))
    return result.scalar_one_or_none()


async def any_organisation_exists(session: AsyncSession) -> bool:
    result = await session.execute(select(func.count()).select_from(Organisation))
    return (result.scalar_one() or 0) > 0


async def seed_demo_fleet(
    session: AsyncSession,
    settings: Settings,
) -> tuple[Organisation, list[Site], list[Generator], str | None]:
    """Create the demo organisation, its sites and its generators.

    Idempotent: if the slug already exists the existing fleet is returned
    untouched and the returned key is None, because the plaintext of an
    already-issued key cannot be recovered.
    """
    existing = await organisation_by_slug(session, settings.seed_org_slug)
    if existing is not None:
        sites = list(
            (await session.execute(select(Site).where(Site.organisation_id == existing.id)))
            .scalars()
            .all()
        )
        generators = list(
            (
                await session.execute(
                    select(Generator).where(Generator.organisation_id == existing.id)
                )
            )
            .scalars()
            .all()
        )
        return existing, sites, generators, None

    rng = random.Random(settings.sim_seed)

    organisation = Organisation(
        id=uuid.uuid4(),
        name=settings.seed_org_name,
        slug=settings.seed_org_slug,
    )
    session.add(organisation)

    # The bootstrap key is taken from configuration rather than generated, so
    # the value printed in .env.example is the value that actually works.
    plaintext = settings.bootstrap_api_key
    session.add(
        ApiKey(
            id=uuid.uuid4(),
            organisation_id=organisation.id,
            key_hash=hash_key(plaintext),
            prefix=plaintext[:12],
            label="bootstrap",
        )
    )

    sites: list[Site] = []
    for name, latitude, longitude, profile, address in LOCATIONS:
        site = Site(
            id=uuid.uuid4(),
            organisation_id=organisation.id,
            name=name,
            profile=profile,
            latitude=latitude,
            longitude=longitude,
            address=address,
        )
        sites.append(site)
        session.add(site)

    # Commissioning date for every seeded sensor. Fixed rather than "now" so
    # the seed stays deterministic across runs.
    calibrated_at = datetime(2026, 1, 15, tzinfo=UTC)

    tanks: list[Tank] = []

    # --- site bulk storage ---
    for site in sites:
        count = BULK_TANK_COUNT[site.profile]
        # The profile total is the site's whole reserve; splitting it across
        # several vessels keeps the site total honest rather than multiplying it.
        each = default_bulk_capacity_l(site.profile) / count
        for number in range(1, count + 1):
            tanks.append(
                Tank(
                    id=uuid.uuid4(),
                    organisation_id=organisation.id,
                    site_id=site.id,
                    generator_id=None,
                    name=f"{site.name} Bulk {number}",
                    kind=TankKind.BULK,
                    capacity_l=round(each, 0),
                    # Bulk is reordered earlier than a day tank: a tanker takes
                    # hours to arrive, and running the reserve dry strands every
                    # generator on site at once.
                    reorder_threshold_pct=rng.choice((30.0, 35.0, 40.0)),
                    sensor_model=BULK_SENSOR_MODEL,
                    sensor_serial=f"ESC-B-{site.name[:3].upper()}-{number:02d}",
                    calibrated_at=calibrated_at,
                )
            )

    generators: list[Generator] = []
    for index in range(settings.seed_generator_count):
        site = sites[index % len(sites)]
        kva = rng.choice(KVA_BY_PROFILE[site.profile])

        # Day tank sized off the site profile, then nudged up for larger units
        # so a 100 kVA set doesn't need topping up twice as often as a 40 kVA
        # one. Never below the 1000 L floor the platform targets.
        capacity = default_tank_capacity_l(site.profile) * (1.0 + (kva - 25.0) / 300.0)
        capacity = max(MIN_TANK_CAPACITY_L, round(capacity, 0))

        generator = Generator(
            id=uuid.uuid4(),
            organisation_id=organisation.id,
            site_id=site.id,
            name=f"{site.name} GEN-{index // len(sites) + 1}",
            serial=f"FP-{int(kva):03d}-{index + 1:04d}",
            kva_rating=kva,
            power_factor=0.8,
            tank_capacity_l=capacity,
            reorder_threshold_pct=rng.choice((20.0, 25.0, 30.0)),
            status=GeneratorStatus.ACTIVE,
        )
        generators.append(generator)

        tanks.append(
            Tank(
                id=uuid.uuid4(),
                organisation_id=organisation.id,
                site_id=site.id,
                generator_id=generator.id,
                name=f"{generator.name} Day Tank",
                kind=TankKind.DAY,
                capacity_l=capacity,
                reorder_threshold_pct=generator.reorder_threshold_pct,
                sensor_model=DAY_SENSOR_MODEL,
                sensor_serial=f"ESC-D-{index + 1:04d}",
                calibrated_at=calibrated_at,
            )
        )

    session.add_all(generators)
    # Tanks reference generators, so both sides must exist before the FK is
    # checked at flush.
    await session.flush()
    session.add_all(tanks)
    await session.flush()

    return organisation, sites, generators, plaintext
