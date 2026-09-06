"""Guard for the non-blocking contract (see backend/db.py).

psycopg is a blocking driver, so every /api handler must be a sync `def`:
FastAPI then runs it in its threadpool and requests overlap. An `async def`
handler would run the query on the event loop and serialise every other
request behind it, which would make the connection pool decorative.
"""

from __future__ import annotations

import inspect

from backend.main import app


def test_api_handlers_are_sync():
    offenders = [
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api")
        and inspect.iscoroutinefunction(getattr(route, "endpoint", None))
    ]
    assert offenders == [], (
        "these handlers would run blocking psycopg calls on the event loop: "
        f"{offenders}"
    )
