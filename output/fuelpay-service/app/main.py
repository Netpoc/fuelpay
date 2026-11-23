"""FastAPI application entry point.

On startup the service makes sure there is something to look at: it seeds the
demo fleet and backfills history if the database is empty. Both steps are
idempotent, so a restart neither duplicates data nor wipes it.

Migrations are NOT run here — `docker compose` runs `alembic upgrade head`
before the server starts. Schema changes belong to a deploy step, not to
whichever replica happened to boot first.
"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.config import Settings, get_settings
from app.db import dispose_engine, get_sessionmaker
from app.scheduler import create_scheduler
from app.services.backfill import backfill_site_specs, load_site_specs
from app.services.demo_jobs import recover_interrupted
from app.services.fleet import seed_demo_fleet

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s: %(message)s")
logger = logging.getLogger("fuelpay")

DESCRIPTION = """
Simulated fuel telemetry for 25–100 kVA diesel generators.

Every reading carries time, fuel volume and GPS position. Consumption follows a
published specific-fuel-consumption curve rather than a flat litres-per-hour
figure, so lightly loaded units burn proportionally more — as real ones do.

Authenticate with `X-API-Key` or `Authorization: Bearer <key>`.
"""


async def _bootstrap(settings: Settings) -> None:
    """Seed the demo fleet and backfill its history, once."""
    async with get_sessionmaker()() as session:
        organisation, sites, generators, plaintext = await seed_demo_fleet(session, settings)

        if plaintext is not None:
            logger.info(
                "seeded organisation %r with %d sites and %d generators",
                organisation.slug,
                len(sites),
                len(generators),
            )
            logger.info("bootstrap API key: %s", plaintext)
        else:
            logger.info("organisation %r already present; skipping seed", organisation.slug)

        specs = await load_site_specs(session, organisation.id)
        readings, events = await backfill_site_specs(
            session,
            specs,
            days=settings.seed_backfill_days,
            until=datetime.now(UTC),
            minutes_per_step=settings.sim_minutes_per_tick,
            seed=settings.sim_seed,
        )
        await session.commit()

        if readings or events:
            logger.info("backfill wrote %d readings and %d events", readings, events)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    if settings.seed_on_startup:
        try:
            await _bootstrap(settings)
        except Exception:
            # A failed seed should not take the API down — the schema may
            # simply be mid-migration. Log it loudly and serve anyway.
            logger.exception("bootstrap failed; continuing without seed data")

    scheduler = None
    if settings.sim_enabled:
        scheduler = create_scheduler(settings)
        scheduler.start()
        logger.info(
            "live ticker started: every %ds, advancing %d simulated minutes per step",
            settings.sim_tick_seconds,
            settings.sim_minutes_per_tick,
        )
        try:
            resumed = await recover_interrupted(settings)
            if resumed:
                logger.info("resumed %d interrupted demo backfill(s)", resumed)
        except Exception:
            logger.exception("could not resume demo backfills")
    else:
        logger.info("live ticker disabled (FUELPAY_SIM_ENABLED=false)")

    yield

    if scheduler is not None:
        # wait=False: a tick in flight holds a transaction-scoped lock that is
        # released by the rollback when its connection is torn down, so there
        # is nothing to wait for and shutdown stays prompt.
        scheduler.shutdown(wait=False)

    await dispose_engine()


app = FastAPI(
    title="FuelPay Telemetry API",
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
)

# The browser client is served from a different origin in development, so
# without this every /v1 call fails before it reaches a route.
#
# Do NOT add GZipMiddleware to this app: it buffers responses, which would
# break the SSE stream in app/api/stream.py.
_cors_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_settings.cors_origin_list,
    allow_credentials=_cors_settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    # Last-Event-ID is not a CORS-safelisted request header. It is only sent on
    # an SSE *reconnect*, so omitting it yields a bug that appears after the
    # first network blip rather than on first connect.
    allow_headers=[
        "X-API-Key",
        "X-Admin-Token",
        "Authorization",
        "Content-Type",
        "Last-Event-ID",
    ],
    max_age=600,
)

app.include_router(api_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": "fuelpay-telemetry",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/health",
    }
