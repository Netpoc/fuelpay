from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.tuning import RefillWindow, TheftTuning


class Settings(BaseSettings):
    """Environment-driven configuration. All vars carry the FUELPAY_ prefix."""

    model_config = SettingsConfigDict(
        env_prefix="FUELPAY_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://fuelpay:fuelpay@localhost:5432/fuelpay"
    echo_sql: bool = False

    # --- browser access ---
    # Declared as a comma-separated string rather than list[str] because
    # pydantic-settings parses list-typed fields from the environment as JSON,
    # so FUELPAY_CORS_ALLOW_ORIGINS=http://localhost:5173 would raise at import.
    cors_allow_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # We authenticate with a header, not a cookie. Turning this on would make
    # the browser reject `allow_origins=["*"]` and stop honouring a wildcard
    # Access-Control-Allow-Headers, forcing exact enumeration everywhere.
    cors_allow_credentials: bool = False

    # --- live ticking simulator ---
    sim_enabled: bool = True
    sim_tick_seconds: int = 300
    sim_minutes_per_tick: int = 5
    sim_seed: int = 20260729

    # --- simulated incident rates ---
    # Defaults reproduce the behaviour these were hard-coded to in
    # app/simulation/engine.py. Raise the theft probability for a demo where
    # siphons need to show up in minutes rather than over days.
    sim_theft_probability_per_day: float = 0.015
    sim_theft_volume_min_fraction: float = 0.20
    sim_theft_volume_max_fraction: float = 0.40
    # Raising the probability alone is not enough to see a siphon in a midday
    # demo — the window has to move too.
    sim_theft_window_start_hour: int = 22
    sim_theft_window_end_hour: int = 4
    sim_refill_window_start_hour: int = 8
    sim_refill_window_end_hour: int = 17

    # --- auth ---
    bootstrap_api_key: str = "dev-local-key-change-me"
    # Operator credential for /v1/platform (coupons, demo tenants). Separate
    # from any tenant key so no organisation, demo or otherwise, can mint
    # coupons for itself. Empty disables the platform API entirely.
    platform_admin_key: str = ""

    # --- coupon-gated demo accounts ---
    # History generated behind `now` for each entity a prospect creates.
    demo_backfill_days: int = 30
    # Backfills run on the API's event loop (CPU work in a thread); this caps
    # how many run at once so a burst of signups cannot starve the ticker.
    demo_backfill_concurrency: int = 2
    # An expired demo stops working immediately; its data is kept this long
    # afterwards in case sales want to extend it, then purged.
    demo_purge_grace_hours: int = 24
    demo_expiry_check_minutes: int = 60
    # Per-client-IP attempts at /v1/demo/redeem. Coupon caps are the real
    # limiter; this only blunts code guessing.
    demo_redeem_per_minute: int = 5

    # --- outbound events ---
    webhook_url: str = ""
    webhook_timeout_seconds: float = 5.0

    # --- demo fleet ---
    # Seeded on first startup when the database has no organisations, so a
    # fresh `docker compose up` yields a service with data already in it.
    seed_on_startup: bool = True
    seed_org_name: str = "FuelPay Demo Energy"
    seed_org_slug: str = "demo"
    seed_generator_count: int = 12
    # Days of history generated behind `now` on first startup. 60 days x 12
    # generators at 5-minute resolution is ~207k readings, written in 2000-row
    # batches. Paid once, on the first boot against an empty database.
    seed_backfill_days: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        """Split the configured origins. `*` passes through as the wildcard."""
        raw = self.cors_allow_origins.strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def theft_tuning(self) -> TheftTuning:
        return TheftTuning(
            probability_per_day=self.sim_theft_probability_per_day,
            volume_min_fraction=self.sim_theft_volume_min_fraction,
            volume_max_fraction=self.sim_theft_volume_max_fraction,
            window_start_hour=self.sim_theft_window_start_hour,
            window_end_hour=self.sim_theft_window_end_hour,
        )

    @property
    def refill_window(self) -> RefillWindow:
        return RefillWindow(
            start_hour=self.sim_refill_window_start_hour,
            end_hour=self.sim_refill_window_end_hour,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
