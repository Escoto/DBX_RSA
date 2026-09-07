"""Pool saturation is backpressure, not a server fault (ADR-008).

Two things used to be accidental: FastAPI's threadpool defaulted to anyio's
40 threads with no relationship to `PG_POOL_MAX=10`, and a saturated pool's
`psycopg_pool.PoolTimeout` fell into the catch-all handler and came back as an
opaque `500`. This file pins both fixes: the threadpool is sized from
`pg_pool_max` at startup, and `PoolTimeout` gets its own `503` with a
`Retry-After` header instead of the generic handler.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import anyio.to_thread
import psycopg_pool
import pytest
from fastapi.testclient import TestClient

from backend import db, main
from backend.config import Settings, settings
from backend.main import app


@pytest.fixture
def quiet_client() -> TestClient:
    """A client that returns 500s instead of re-raising (see test_app_shell.py)."""
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------- 503 response


def test_pool_timeout_returns_503_not_500(client, monkeypatch):
    monkeypatch.setattr(
        db,
        "query",
        lambda *a, **k: (_ for _ in ()).throw(
            psycopg_pool.PoolTimeout("couldn't get a connection")
        ),
    )

    res = client.get("/api/movies")

    assert res.status_code == 503


def test_pool_timeout_body_is_structured_and_names_the_cause(client, monkeypatch):
    monkeypatch.setattr(
        db,
        "query",
        lambda *a, **k: (_ for _ in ()).throw(
            psycopg_pool.PoolTimeout("couldn't get a connection")
        ),
    )

    body = client.get("/api/movies").json()

    assert body["error"] == "PoolTimeout"
    assert "saturated" in body["detail"].lower()


def test_pool_timeout_sends_a_retry_after_header(client, monkeypatch):
    monkeypatch.setattr(
        db,
        "query",
        lambda *a, **k: (_ for _ in ()).throw(psycopg_pool.PoolTimeout("timeout")),
    )

    res = client.get("/api/movies")

    assert res.headers["retry-after"] == str(main.POOL_RETRY_AFTER_SECONDS)


def test_pool_timeout_from_the_booking_write_path_is_also_503(client, monkeypatch):
    """The handler is global: any router, not just reads, gets the same 503."""
    monkeypatch.setattr(
        db,
        "query",
        lambda *a, **k: (_ for _ in ()).throw(psycopg_pool.PoolTimeout("timeout")),
    )

    res = client.post(
        "/api/bookings",
        json={
            "showtime_id": "st-1",
            "seat_ids": ["seat-1"],
            "customer": {"name": "A", "email": "a@example.com"},
        },
    )

    assert res.status_code == 503
    assert res.json()["error"] == "PoolTimeout"


def test_a_plain_exception_still_gets_the_generic_500(quiet_client, monkeypatch):
    """PoolTimeout gets its own handler; every other failure is unchanged."""
    monkeypatch.setattr(
        db, "query", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    res = quiet_client.get("/api/movies")

    assert res.status_code == 500
    assert res.json()["error"] == "RuntimeError"


# ---------------------------------------------------------------- /api/health visibility


def test_health_reports_the_pool_and_threadpool_relationship(client, monkeypatch):
    # Fail fast at the first credential step; these fields are set before it
    # and must not depend on a live Lakebase.
    monkeypatch.setattr(
        db, "_client", lambda: (_ for _ in ()).throw(RuntimeError("no creds"))
    )

    body = client.get("/api/health").json()

    assert body["pg_pool_max"] == settings.pg_pool_max
    assert body["pg_pool_timeout"] == settings.pg_pool_timeout
    assert body["api_thread_pool_size"] == settings.api_thread_pool_size


# ---------------------------------------------------------------- threadpool sizing


def test_configure_thread_pool_sets_the_anyio_limiter(monkeypatch):
    monkeypatch.setattr(settings, "api_thread_pool_size", 12)
    monkeypatch.setattr(settings, "pg_pool_max", 10)

    async def _run():
        main._configure_thread_pool()
        return anyio.to_thread.current_default_thread_limiter().total_tokens

    assert asyncio.run(_run()) == 12


def test_configure_thread_pool_returns_the_size_it_set(monkeypatch):
    monkeypatch.setattr(settings, "api_thread_pool_size", 17)

    async def _run():
        return main._configure_thread_pool()

    assert asyncio.run(_run()) == 17


def test_configure_thread_pool_warns_when_smaller_than_the_db_pool(
    monkeypatch, caplog
):
    monkeypatch.setattr(settings, "api_thread_pool_size", 3)
    monkeypatch.setattr(settings, "pg_pool_max", 10)

    async def _run():
        main._configure_thread_pool()

    with caplog.at_level("WARNING", logger="backend.main"):
        asyncio.run(_run())

    assert any("idle" in rec.message for rec in caplog.records)


def test_configure_thread_pool_is_quiet_when_sized_correctly(monkeypatch, caplog):
    monkeypatch.setattr(settings, "api_thread_pool_size", 14)
    monkeypatch.setattr(settings, "pg_pool_max", 10)

    async def _run():
        main._configure_thread_pool()

    with caplog.at_level("WARNING", logger="backend.main"):
        asyncio.run(_run())

    assert caplog.records == []


# ---------------------------------------------------------------- deliberate defaults


def test_default_thread_pool_size_derives_from_pool_max(monkeypatch):
    monkeypatch.delenv("API_THREAD_POOL_SIZE", raising=False)
    monkeypatch.setenv("PG_POOL_MAX", "6")

    s = Settings()

    assert s.pg_pool_max == 6
    assert s.api_thread_pool_size == 10  # pool_max + fixed headroom


def test_default_thread_pool_size_tracks_a_larger_pool(monkeypatch):
    monkeypatch.delenv("API_THREAD_POOL_SIZE", raising=False)
    monkeypatch.setenv("PG_POOL_MAX", "25")

    assert Settings().api_thread_pool_size == 29


def test_thread_pool_size_env_override_wins(monkeypatch):
    monkeypatch.setenv("PG_POOL_MAX", "6")
    monkeypatch.setenv("API_THREAD_POOL_SIZE", "50")

    assert Settings().api_thread_pool_size == 50


def test_pool_timeout_defaults_to_ten_seconds(monkeypatch):
    monkeypatch.delenv("PG_POOL_TIMEOUT", raising=False)

    assert Settings().pg_pool_timeout == 10.0


def test_pool_timeout_env_override_wins(monkeypatch):
    monkeypatch.setenv("PG_POOL_TIMEOUT", "3.5")

    assert Settings().pg_pool_timeout == 3.5


# ---------------------------------------------------------------- db.py wiring


def test_pool_is_built_with_the_configured_timeout(monkeypatch):
    captured = {}

    def _record(**kw):
        captured.update(kw)
        return MagicMock(name="pool")

    monkeypatch.setattr(db, "ConnectionPool", _record)
    monkeypatch.setattr(settings, "pg_pool_timeout", 3.5)

    db.get_pool()

    assert captured["timeout"] == 3.5
