"""Shared fixtures for the API tests.

The tests exercise the real FastAPI app and the real Pydantic models; only
`backend.db` is replaced. That boundary is deliberate: everything above it
(routing, validation, response shaping, error translation) is what regressions
actually break, and everything below it needs a live Lakebase.

Two rules make the suite safe to run anywhere, with no credentials:

* `TestClient(app)` is used WITHOUT a `with` block, so Starlette never runs the
  lifespan and the connection pool is never opened. A test that wants the
  lifespan must opt in explicitly.
* `reset_db_globals` clears the module-level caches in `backend.db` between
  tests, so a cached token or host cannot leak from one test into the next.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import db
from backend.config import settings
from backend.main import app


class DbStub:
    """Stand-in for `backend.db.query`, matching on SQL substrings.

    Substring matching rather than a call-ordered queue: it keeps each test
    readable about *which* query it is stubbing, and it does not break when an
    unrelated query is added to a handler. Rules are checked in registration
    order, so register the most specific first.
    """

    def __init__(self) -> None:
        self.rules: list[tuple[str, object]] = []
        self.calls: list[tuple[str, tuple | None]] = []

    def on(self, sql_fragment: str, result):
        """Return `result` for any query containing `sql_fragment`.

        `result` may be a callable taking the params tuple, for tests that
        need the answer to depend on what was asked.
        """
        self.rules.append((sql_fragment, result))
        return self

    def query(self, sql: str, params: tuple | None = None) -> list[dict]:
        normalized = " ".join(sql.split())
        self.calls.append((normalized, params))
        for fragment, result in self.rules:
            if " ".join(fragment.split()) in normalized:
                return result(params) if callable(result) else result
        raise AssertionError(
            f"DbStub got an unstubbed query: {normalized!r} params={params!r}"
        )

    def last_sql(self) -> str:
        return self.calls[-1][0]

    def last_params(self) -> tuple | None:
        return self.calls[-1][1]

    def sql_for(self, fragment: str) -> str:
        """The first recorded query containing `fragment`; asserts it happened."""
        for sql, _params in self.calls:
            if " ".join(fragment.split()) in sql:
                return sql
        raise AssertionError(f"no query matched {fragment!r}; got {self.calls!r}")

    def params_for(self, fragment: str) -> tuple | None:
        for sql, params in self.calls:
            if " ".join(fragment.split()) in sql:
                return params
        raise AssertionError(f"no query matched {fragment!r}; got {self.calls!r}")


@pytest.fixture(autouse=True)
def reset_db_globals():
    """Clear backend.db's module caches around every test."""
    db._token = None
    db._token_created_at = 0.0
    db._host = None
    db._ws = None
    db._pool = None
    yield
    db._token = None
    db._token_created_at = 0.0
    db._host = None
    db._ws = None
    db._pool = None


@pytest.fixture
def stub(monkeypatch) -> DbStub:
    """A DbStub wired into backend.db.query."""
    s = DbStub()
    monkeypatch.setattr(db, "query", s.query)
    return s


@pytest.fixture
def client() -> TestClient:
    """The real app. No lifespan, so no pool is opened."""
    return TestClient(app)


@pytest.fixture
def no_pool(monkeypatch):
    """Force the non-pooled code path in backend.db."""
    monkeypatch.setattr(settings, "pg_pool_enabled", False)
