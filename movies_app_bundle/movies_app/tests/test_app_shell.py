"""The bits of `main.py` that are neither a router nor the database.

Ordering here is subtle and easy to break: StaticFiles is mounted at `/`, so it
would swallow every route registered after it, and the 404 handler serves both
the SPA's history-mode fallback and the API's genuine misses. A change to the
order of the last twenty lines of `main.py` fails these tests rather than
quietly returning HTML to a JSON client.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.main import DIST_DIR, app

needs_dist = pytest.mark.skipif(
    not DIST_DIR.is_dir(),
    reason="frontend/dist is built on the Apps runtime at deploy time (ADR-004)",
)


@pytest.fixture
def quiet_client() -> TestClient:
    """A client that returns 500s instead of re-raising, to test the handler."""
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------- 404 routing


def test_unknown_api_path_is_json_not_html(client):
    """An unrouted /api path falls through the SPA mount; it must not get HTML.

    The detail is Starlette's own "Not Found" — the handler passes through
    whatever raised, and nothing under /api routed this request.
    """
    res = client.get("/api/nope")

    assert res.status_code == 404
    assert res.headers["content-type"].startswith("application/json")
    assert res.json() == {"detail": "Not Found"}


def test_api_404_keeps_the_routers_message(client, stub):
    """The SPA surfaces `detail` verbatim, so it must not be flattened."""
    stub.on("FROM movies WHERE movie_id", [])

    assert client.get("/api/movies/nope").json()["detail"] == "Movie not found"


@needs_dist
def test_unknown_spa_path_serves_index(client):
    """vue-router uses history mode; deep links must boot the app."""
    res = client.get("/bookings/12345678-1234-5678-1234-567812345678")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert "<div id=\"app\">" in res.text or "id=app" in res.text


@needs_dist
def test_spa_root_is_served(client):
    res = client.get("/")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")


# ---------------------------------------------------------------- error handler


def test_unhandled_api_error_returns_a_structured_500(quiet_client, monkeypatch):
    monkeypatch.setattr(
        db, "query", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pool timeout"))
    )

    res = quiet_client.get("/api/movies")

    assert res.status_code == 500
    body = res.json()
    # Prototype behaviour, documented in main.py: the real cause is echoed so
    # the SPA's error box is useful without runtime log access.
    assert body["error"] == "RuntimeError"
    assert "pool timeout" in body["message"]
    assert "pool timeout" in body["detail"]


def test_unhandled_error_detail_is_truncated(quiet_client, monkeypatch):
    monkeypatch.setattr(
        db, "query", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x" * 2000))
    )

    body = quiet_client.get("/api/movies").json()

    assert len(body["message"]) == 500


# ---------------------------------------------------------------- API surface


def test_openapi_lists_the_documented_contract(client):
    """CLAUDE.md §4.5 is the contract; /docs is what the panel will open."""
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths) >= {
        "/api/health",
        "/api/movies",
        "/api/movies/{movie_id}",
        "/api/theaters",
        "/api/showtimes",
        "/api/showtimes/{showtime_id}/seats",
        "/api/bookings",
        "/api/bookings/{booking_id}",
    }


def test_booking_post_documents_its_201(client):
    post = client.get("/openapi.json").json()["paths"]["/api/bookings"]["post"]

    assert "201" in post["responses"]
