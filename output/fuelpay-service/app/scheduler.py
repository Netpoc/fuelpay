"""Scheduling for the live ticker.

APScheduler on the running event loop rather than a separate worker process:
the tick is a handful of queries and some arithmetic, and keeping it in-process
means `docker compose up` yields a service that is already producing data. A
real deployment with many replicas would move this out — the advisory lock in
`services.ticker` already makes that safe, since every extra replica simply
skips.
"""

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import Settings
from app.db import get_sessionmaker
from app.services.demo_jobs import expire_demos
from app.services.ticker import run_tick

logger = logging.getLogger(__name__)

JOB_ID = "fuelpay-live-tick"
EXPIRY_JOB_ID = "fuelpay-demo-expiry"


async def _tick_job(settings: Settings) -> None:
    """One scheduled tick, in its own session.

    Never raises: an exception escaping here would be logged by APScheduler and
    the job would keep running, but the traceback reads better from our side,
    and a transient database blip should not look like a scheduler fault.
    """
    try:
        async with get_sessionmaker()() as session:
            await run_tick(session, settings, datetime.now(UTC))
    except Exception:
        logger.exception("live tick failed; will retry on the next interval")


async def _expiry_job(settings: Settings) -> None:
    """Revoke and, after the grace period, purge expired demo tenants."""
    try:
        async with get_sessionmaker()() as session:
            await expire_demos(session, settings)
    except Exception:
        logger.exception("demo expiry failed; will retry on the next interval")


def create_scheduler(settings: Settings) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _tick_job,
        trigger=IntervalTrigger(seconds=settings.sim_tick_seconds),
        args=[settings],
        id=JOB_ID,
        # A tick advances to wall-clock, so a queued second copy would find
        # nothing to do at best and race the first at worst.
        max_instances=1,
        coalesce=True,
        # Run late ticks instead of dropping them. Lateness is not a reason to
        # skip when the work is "catch up to now".
        misfire_grace_time=None,
    )
    scheduler.add_job(
        _expiry_job,
        trigger=IntervalTrigger(minutes=settings.demo_expiry_check_minutes),
        args=[settings],
        id=EXPIRY_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
