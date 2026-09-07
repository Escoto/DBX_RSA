"""GET /api/health — the endpoint that diagnosed ADR-005.

It walks the credential chain one step at a time (SDK auth -> host -> user ->
token -> connect) and stops at the first failure, so a 500 on the deployed app
can be localised without runtime log access. The tests pin that behaviour: each
step must report `degraded` and must NOT report the steps after it, because
"the response stopped here" is the whole diagnostic signal.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend import db
from backend.config import settings
from tests.test_db import FakeConnection


@pytest.fixture
def healthy(monkeypatch):
    """Every step of the chain succeeds."""
    monkeypatch.setattr(
        db, "_client", lambda: SimpleNamespace(config=SimpleNamespace(auth_type="oauth"))
    )
    monkeypatch.setattr(db, "_get_host", lambda: "instance.databricks.com")
    monkeypatch.setattr(db, "_get_user", lambda: "sp-client-id")
    monkeypatch.setattr(db, "_get_token", lambda: "token-1")
    monkeypatch.setattr(db, "get_connection", lambda: FakeConnection())
    monkeypatch.setattr(settings, "pg_pool_enabled", False)


def _fail(exc):
    def _raise(*a, **k):
        raise exc

    return _raise


def test_health_ok(client, healthy):
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert body["db"] == "connected"
    assert body["sdk_auth_type"] == "oauth"
    assert body["resolved_user"] == "sp-client-id"
    assert body["token_ok"] is True
    assert body["token_source"] == "generate_database_credential"


def test_health_reports_the_static_settings(client, healthy):
    body = client.get("/api/health").json()

    assert body["instance"] == settings.lakebase_instance
    assert body["database"] == settings.lakebase_database
    assert body["schema"] == settings.lakebase_schema


def test_health_reports_which_env_vars_were_injected(client, healthy, monkeypatch):
    """ADR-005 turned on exactly this question: did the platform inject PGHOST?"""
    monkeypatch.setattr(settings, "pghost", "injected.databricks.com")
    monkeypatch.setattr(settings, "pguser", None)

    body = client.get("/api/health").json()

    assert body["pghost_injected"] is True
    assert body["pguser_injected"] is False


def test_health_token_source_reflects_pgpassword(client, healthy, monkeypatch):
    monkeypatch.setattr(settings, "pgpassword", "static-secret")

    body = client.get("/api/health").json()

    assert body["token_source"] == "PGPASSWORD"
    assert body["pgpassword_injected"] is True


def test_sdk_failure_stops_the_chain(client, healthy, monkeypatch):
    monkeypatch.setattr(db, "_client", _fail(RuntimeError("no credentials")))

    body = client.get("/api/health").json()

    assert body["status"] == "degraded"
    assert "RuntimeError: no credentials" in body["sdk_error"]
    assert "resolved_host" not in body


def test_host_failure_stops_the_chain(client, healthy, monkeypatch):
    """The ADR-005 signature: the SP could not call get_database_instance."""
    monkeypatch.setattr(db, "_get_host", _fail(PermissionError("denied")))

    body = client.get("/api/health").json()

    assert body["status"] == "degraded"
    assert "PermissionError: denied" in body["host_error"]
    assert "resolved_user" not in body
    assert "db" not in body


def test_user_failure_stops_the_chain(client, healthy, monkeypatch):
    monkeypatch.setattr(db, "_get_user", _fail(RuntimeError("no user")))

    body = client.get("/api/health").json()

    assert body["status"] == "degraded"
    assert "no user" in body["user_error"]
    assert "token_ok" not in body


def test_token_failure_stops_the_chain(client, healthy, monkeypatch):
    monkeypatch.setattr(db, "_get_token", _fail(RuntimeError("mint failed")))

    body = client.get("/api/health").json()

    assert body["status"] == "degraded"
    assert "mint failed" in body["token_error"]
    assert "db" not in body


def test_connect_failure_is_degraded_but_still_reports_the_earlier_steps(
    client, healthy, monkeypatch
):
    """A connect failure is the one case where the earlier detail matters most."""
    monkeypatch.setattr(db, "get_connection", _fail(OSError("timeout")))

    body = client.get("/api/health").json()

    assert body["status"] == "degraded"
    assert body["db"].startswith("error: OSError")
    assert body["resolved_host"] == "instance.databricks.com"
    assert body["token_ok"] is True


def test_health_long_host_is_truncated(client, healthy, monkeypatch):
    monkeypatch.setattr(db, "_get_host", lambda: "h" * 80)

    body = client.get("/api/health").json()

    assert body["resolved_host"].endswith("...")
    assert len(body["resolved_host"]) == 43


def test_health_includes_pool_stats_when_pooling_is_on(client, healthy, monkeypatch):
    pool = MagicMock()
    pool.get_stats.return_value = {
        "pool_size": 3,
        "pool_available": 3,
        "requests_waiting": 0,
        "connections_num": 3,
    }
    monkeypatch.setattr(settings, "pg_pool_enabled", True)
    monkeypatch.setattr(db, "get_pool", lambda: pool)

    body = client.get("/api/health").json()

    assert body["pool_stats"]["pool_size"] == 3
    assert body["pool_stats"]["requests_waiting"] == 0


def test_health_survives_a_broken_pool(client, healthy, monkeypatch):
    monkeypatch.setattr(settings, "pg_pool_enabled", True)
    monkeypatch.setattr(db, "get_pool", _fail(RuntimeError("PoolClosed")))

    body = client.get("/api/health").json()

    assert body["db"] == "connected"
    assert "PoolClosed" in body["pool_stats"]


def test_health_omits_pool_stats_when_pooling_is_off(client, healthy):
    assert "pool_stats" not in client.get("/api/health").json()


def test_health_never_returns_the_token(client, healthy):
    """token_ok is a boolean on purpose; the credential must not be echoed."""
    assert "token-1" not in client.get("/api/health").text
