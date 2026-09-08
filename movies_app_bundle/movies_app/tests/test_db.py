"""backend/db.py — credential resolution and connection lifetime.

Two classes of regression are guarded here.

*Credentials.* Host, user and token each have a documented precedence
(`PGHOST` over the workspace API, `PGUSER` over `DATABRICKS_CLIENT_ID` over the
signed-in user, `PGPASSWORD` over `generate_database_credential`). ADR-005 was
caused by getting the host rule wrong on the platform, and it cost an outage
that could not be reproduced locally, so each branch is pinned.

*Connection lifetime.* The same ADR fixed a psycopg 3 leak: `query()`
opened a connection and never closed it. A leak does not fail a
test by itself — it exhausts the server hours later — so the tests assert
`close()` was called, including on the exception path.

No test here reaches the network: `WorkspaceClient` and the connection factory
are both replaced.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import psycopg
import pytest

from backend import db
from backend.config import settings


# ---------------------------------------------------------------- fakes


class FakeCursor:
    def __init__(self, rows=None, description=None, rowcount=1):
        self.rows = rows if rows is not None else []
        self.description = description or [("col",)]
        self.rowcount = rowcount
        self.executed: list[tuple] = []
        self.raise_on_execute: Exception | None = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.raise_on_execute:
            raise self.raise_on_execute

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, cursor: FakeCursor | None = None):
        self._cursor = cursor or FakeCursor()
        self.closed = False
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


@pytest.fixture
def fake_ws(monkeypatch):
    """Replace WorkspaceClient so nothing authenticates."""
    ws = MagicMock()
    ws.database.get_database_instance.return_value = SimpleNamespace(
        read_write_dns="instance.database.cloud.databricks.com"
    )
    ws.database.generate_database_credential.return_value = SimpleNamespace(
        token="token-1"
    )
    ws.current_user.me.return_value = SimpleNamespace(user_name="ra.escoto@slalom.com")
    monkeypatch.setattr(db, "WorkspaceClient", lambda *a, **k: ws)
    return ws


@pytest.fixture
def clean_env(monkeypatch):
    """No platform-injected PG*/client-id values unless a test sets them."""
    monkeypatch.setattr(settings, "pghost", None)
    monkeypatch.setattr(settings, "pguser", None)
    monkeypatch.setattr(settings, "pgpassword", None)
    monkeypatch.delenv("DATABRICKS_CLIENT_ID", raising=False)


# ---------------------------------------------------------------- host


def test_pghost_wins_and_skips_the_workspace_api(fake_ws, clean_env, monkeypatch):
    """The ADR-005 fix: on the platform the SP cannot call the workspace API."""
    monkeypatch.setattr(settings, "pghost", "injected.databricks.com")

    assert db._get_host() == "injected.databricks.com"
    fake_ws.database.get_database_instance.assert_not_called()


def test_host_falls_back_to_the_sdk(fake_ws, clean_env):
    assert db._get_host() == "instance.database.cloud.databricks.com"
    fake_ws.database.get_database_instance.assert_called_once_with(
        settings.lakebase_instance
    )


def test_host_is_cached(fake_ws, clean_env):
    db._get_host()
    db._get_host()

    assert fake_ws.database.get_database_instance.call_count == 1


# ---------------------------------------------------------------- user


def test_pguser_wins(fake_ws, clean_env, monkeypatch):
    monkeypatch.setattr(settings, "pguser", "explicit-user")

    assert db._get_user() == "explicit-user"


def test_user_falls_back_to_client_id(fake_ws, clean_env, monkeypatch):
    """On Apps the Postgres role is named for the SP client id."""
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "2a26812a-1b82-4879-9487-6eb43f7ad56b")

    assert db._get_user() == "2a26812a-1b82-4879-9487-6eb43f7ad56b"


def test_user_falls_back_to_signed_in_user(fake_ws, clean_env):
    """Locally the identity is the CLI profile's user."""
    assert db._get_user() == "ra.escoto@slalom.com"


# ---------------------------------------------------------------- token


def test_pgpassword_short_circuits_token_minting(fake_ws, clean_env, monkeypatch):
    monkeypatch.setattr(settings, "pgpassword", "static-secret")

    assert db._get_token() == "static-secret"
    fake_ws.database.generate_database_credential.assert_not_called()


def test_token_is_minted_and_cached(fake_ws, clean_env):
    assert db._get_token() == "token-1"
    assert db._get_token() == "token-1"

    assert fake_ws.database.generate_database_credential.call_count == 1


def test_token_refreshes_after_its_lifetime(fake_ws, clean_env, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(db, "time", SimpleNamespace(monotonic=lambda: now[0]))

    db._get_token()
    now[0] += db.TOKEN_LIFETIME_SECONDS - 1
    db._get_token()
    assert fake_ws.database.generate_database_credential.call_count == 1

    now[0] += 2
    fake_ws.database.generate_database_credential.return_value = SimpleNamespace(
        token="token-2"
    )
    assert db._get_token() == "token-2"
    assert fake_ws.database.generate_database_credential.call_count == 2


def test_token_lifetime_stays_inside_the_credential_validity():
    """`generate_database_credential` tokens last about an hour.

    The refresh test above steps time relative to this constant, so it cannot
    notice the constant itself being wrong. This bound is absolute: a cache
    window at or past an hour would hand out expired tokens.
    """
    assert 0 < db.TOKEN_LIFETIME_SECONDS <= 55 * 60


def test_token_request_is_scoped_to_the_instance(fake_ws, clean_env):
    db._get_token()

    kwargs = fake_ws.database.generate_database_credential.call_args.kwargs
    assert kwargs["instance_names"] == [settings.lakebase_instance]
    assert kwargs["request_id"]


# ---------------------------------------------------------------- connection kwargs


def test_pooled_connection_carries_the_lakebase_settings(
    fake_ws, clean_env, monkeypatch
):
    """The pool builds connections through this override, not through connect()."""
    captured = {}

    def _fake_connect(cls, conninfo="", **kwargs):
        captured.update(kwargs)
        return "connection"

    monkeypatch.setattr(settings, "pghost", "injected.databricks.com")
    monkeypatch.setattr(psycopg.Connection, "connect", classmethod(_fake_connect))

    db._LakebaseConnection.connect()

    assert captured["host"] == "injected.databricks.com"
    assert captured["dbname"] == settings.lakebase_database
    assert captured["password"] == "token-1"
    assert captured["sslmode"] == "require"
    # search_path is what lets every query name bare tables.
    assert captured["options"] == f"-c search_path={settings.lakebase_schema}"


def test_get_connection_uses_the_same_credentials(fake_ws, clean_env, monkeypatch):
    captured = {}
    monkeypatch.setattr(settings, "pghost", "injected.databricks.com")
    monkeypatch.setattr(db.psycopg, "connect", lambda **kw: captured.update(kw))

    db.get_connection()

    assert captured["host"] == "injected.databricks.com"
    assert captured["sslmode"] == "require"
    assert captured["options"] == f"-c search_path={settings.lakebase_schema}"


# ---------------------------------------------------------------- leak regression


def test_query_closes_the_connection(no_pool, monkeypatch):
    conn = FakeConnection(FakeCursor(rows=[(1,)], description=[("n",)]))
    monkeypatch.setattr(db, "get_connection", lambda: conn)

    assert db.query("SELECT 1") == [{"n": 1}]
    assert conn.closed, "ADR-005: query() leaked its connection"


def test_query_closes_the_connection_on_error(no_pool, monkeypatch):
    cursor = FakeCursor()
    cursor.raise_on_execute = RuntimeError("boom")
    conn = FakeConnection(cursor)
    monkeypatch.setattr(db, "get_connection", lambda: conn)

    with pytest.raises(RuntimeError):
        db.query("SELECT 1")

    assert conn.closed, "a failing query must still return its connection"


def test_transaction_commits_and_closes(no_pool, monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(db, "get_connection", lambda: conn)

    with db.transaction() as c:
        assert c is conn

    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.closed


def test_transaction_rolls_back_and_closes_on_error(no_pool, monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(db, "get_connection", lambda: conn)

    with pytest.raises(ValueError):
        with db.transaction():
            raise ValueError("booking failed")

    assert conn.rollbacks == 1
    assert conn.commits == 0
    assert conn.closed, "the 409 rollback path must not leak"


# ---------------------------------------------------------------- pooled path


def _fake_pool(conn: FakeConnection):
    pool = MagicMock()

    @contextmanager
    def _connection():
        yield conn

    pool.connection = _connection
    return pool


def test_query_uses_the_pool_when_enabled(monkeypatch):
    conn = FakeConnection(FakeCursor(rows=[(1,)], description=[("n",)]))
    monkeypatch.setattr(settings, "pg_pool_enabled", True)
    monkeypatch.setattr(db, "get_pool", lambda: _fake_pool(conn))
    monkeypatch.setattr(
        db, "get_connection", lambda: pytest.fail("pooled path must not open its own")
    )

    assert db.query("SELECT 1") == [{"n": 1}]
    # The pool's own context manager returns the connection; closing it here
    # would take it out of the pool permanently.
    assert not conn.closed


def test_transaction_rolls_back_on_the_pooled_path(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setattr(settings, "pg_pool_enabled", True)
    monkeypatch.setattr(db, "get_pool", lambda: _fake_pool(conn))

    with pytest.raises(ValueError):
        with db.transaction():
            raise ValueError("booking failed")

    assert conn.rollbacks == 1
    assert not conn.closed


def test_pool_is_created_once(monkeypatch):
    monkeypatch.setattr(db, "ConnectionPool", lambda **kw: MagicMock(name="pool"))

    assert db.get_pool() is db.get_pool()


def test_pool_is_built_unopened_with_the_custom_connection_class(monkeypatch):
    """open=False: the lifespan opens it, so import never touches the network."""
    captured = {}

    def _record(**kw):
        captured.update(kw)
        return MagicMock(name="pool")

    monkeypatch.setattr(db, "ConnectionPool", _record)

    db.get_pool()

    assert captured["open"] is False
    assert captured["connection_class"] is db._LakebaseConnection
    assert captured["max_size"] == settings.pg_pool_max
    # Connections must be recycled before the cached token rotates, and before
    # the credential itself expires — bounded absolutely, not against the
    # constant a mutation could raise.
    assert captured["max_lifetime"] < db.TOKEN_LIFETIME_SECONDS
    assert captured["max_lifetime"] <= 50 * 60
