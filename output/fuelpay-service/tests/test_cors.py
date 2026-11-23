"""Browser access.

The first test in this repo that builds the FastAPI app rather than calling
pure functions. It still needs no database: with seeding and the simulator
disabled the lifespan touches nothing, and `create_async_engine` does not
connect until a query runs.

Two `@lru_cache`s make the setup fussier than it looks — `get_settings` must be
cleared after patching the environment, and `app.main` must be imported
afterwards, or the app is built from whatever configuration a previous test
happened to cache.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

VITE_ORIGIN = "http://localhost:5173"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("FUELPAY_SEED_ON_STARTUP", "false")
    monkeypatch.setenv("FUELPAY_SIM_ENABLED", "false")
    monkeypatch.setenv("FUELPAY_CORS_ALLOW_ORIGINS", f"{VITE_ORIGIN},http://127.0.0.1:5173")

    from app.config import get_settings

    get_settings.cache_clear()

    import app.main

    importlib.reload(app.main)

    with TestClient(app.main.app) as test_client:
        yield test_client

    get_settings.cache_clear()


def test_preflight_allows_the_dev_server_origin(client):
    response = client.options(
        "/v1/summary",
        headers={
            "Origin": VITE_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-api-key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == VITE_ORIGIN


def test_preflight_allows_last_event_id(client):
    """Only sent on an SSE reconnect, so omitting it breaks after the first blip.

    `Last-Event-ID` is not CORS-safelisted. Without it in allow_headers the
    initial stream connect succeeds and every resume fails — a bug that only
    shows up once the network hiccups.
    """
    response = client.options(
        "/v1/summary",
        headers={
            "Origin": VITE_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-api-key,last-event-id",
        },
    )

    assert response.status_code == 200
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "last-event-id" in allowed
    assert "x-api-key" in allowed


def test_actual_response_carries_the_origin_header(client):
    """A 401 still needs the CORS header, or the browser hides the real status."""
    response = client.get("/v1/summary", headers={"Origin": VITE_ORIGIN})

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == VITE_ORIGIN


def test_unlisted_origin_is_refused(client):
    response = client.options(
        "/v1/summary",
        headers={
            "Origin": "https://not-our-app.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_origin_list_splits_and_trims():
    from app.config import Settings

    settings = Settings(cors_allow_origins=" http://a.test , http://b.test ,, ")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


def test_wildcard_origin_passes_through():
    from app.config import Settings

    assert Settings(cors_allow_origins="*").cors_origin_list == ["*"]
