"""Admin-console rules that need no database: passwords, tuning overrides,
overview arithmetic and tenant classification."""

from datetime import UTC, datetime, timedelta

import pytest

from app.api.platform.overview import conversion_rate, fill_days
from app.api.platform.tenants import tenant_kind
from app.models.entities import AdminRole, Organisation
from app.services.admin_auth import (
    BREAK_GLASS,
    AdminActor,
    hash_password,
    password_problem,
    verify_password,
)
from app.services.platform_settings import merge_tuning, validate_tuning
from app.tuning import DEFAULT_VEHICLE, TheftTuning

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


# --- passwords ---


def test_password_round_trip():
    stored = hash_password("Correct-horse-9")
    assert stored.startswith("scrypt$")
    assert verify_password("Correct-horse-9", stored)
    assert not verify_password("correct-horse-9", stored)


def test_hashes_are_salted():
    assert hash_password("Same-password-1") != hash_password("Same-password-1")


@pytest.mark.parametrize("stored", ["", "bcrypt$x", "scrypt$1$2$3$!!$!!", "not even close"])
def test_malformed_hash_never_verifies(stored):
    assert not verify_password("anything", stored)


def test_password_rules():
    assert password_problem("short1A") is not None
    assert password_problem("alllowercaseletters") is not None
    assert password_problem("alllowercase123") is None
    assert password_problem("MixedCaseLetters") is None


def test_roles():
    assert BREAK_GLASS.is_owner
    assert not AdminActor(label="a@b.c", role=AdminRole.STAFF).is_owner


# --- tuning overrides ---


def test_validate_accepts_known_fields():
    clean = validate_tuning(
        {"theft": {"probability_per_day": 0.5}, "vehicle": {"siphon_probability_per_day": 1}}
    )
    assert clean == {
        "theft": {"probability_per_day": 0.5},
        "vehicle": {"siphon_probability_per_day": 1.0},
    }


def test_validate_drops_empty_groups():
    assert validate_tuning({"theft": {}}) == {}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"weather": {}}, "Unknown tuning group"),
        ({"theft": {"nope": 1}}, "Unknown setting"),
        ({"theft": {"probability_per_day": 2}}, "between 0 and 1"),
        ({"theft": {"window_start_hour": 30}}, "between 0 and 23"),
        ({"theft": {"probability_per_day": "high"}}, "must be a number"),
        ({"theft": {"probability_per_day": True}}, "must be a number"),
        ({"vehicle": {"siphon_min_l": 500, "siphon_max_l": 100}}, "cannot exceed"),
        (
            {"theft": {"volume_min_fraction": 0.9}},
            "cannot exceed",
        ),
    ],
)
def test_validate_rejects(overrides, message):
    with pytest.raises(ValueError, match=message):
        validate_tuning(overrides)


def test_merge_applies_and_ignores_stale_fields():
    base = TheftTuning(probability_per_day=0.015)
    theft, vehicle = merge_tuning(
        base,
        {
            "theft": {"probability_per_day": 0.9, "retired_field": 1},
            "vehicle": {"misuse_rate": 3, "short_fill_probability": 0.5},
        },
    )
    assert theft.probability_per_day == 0.9
    assert theft.window_start_hour == base.window_start_hour
    assert vehicle.short_fill_probability == 0.5
    assert vehicle.siphon_probability_per_day == DEFAULT_VEHICLE.siphon_probability_per_day


def test_merge_with_nothing_is_identity():
    base = TheftTuning()
    assert merge_tuning(base, {}) == (base, DEFAULT_VEHICLE)


# --- overview ---


def test_conversion_rate():
    assert conversion_rate(0, 0) is None
    assert conversion_rate(1, 4) == 0.25


def test_fill_days_includes_quiet_days():
    rows = [(NOW - timedelta(days=2), 3), (NOW, 1)]
    days = fill_days(rows, 5, NOW)
    assert [d.count for d in days] == [0, 0, 3, 0, 1]
    assert days[-1].day.date() == NOW.date()


# --- tenants ---


@pytest.mark.parametrize(
    ("is_demo", "expires", "kind"),
    [
        (False, None, "real"),
        (True, NOW + timedelta(days=1), "demo"),
        (True, NOW - timedelta(seconds=1), "expired"),
    ],
)
def test_tenant_kind(is_demo, expires, kind):
    org = Organisation(name="x", slug="x", is_demo=is_demo, demo_expires_at=expires)
    assert tenant_kind(org, NOW) == kind
