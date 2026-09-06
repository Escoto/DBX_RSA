"""Lakebase connection factory.

Credentials: OAuth token minted via the Databricks SDK, cached for 50 minutes
(tokens valid ~1 hour). Host resolved from PGHOST (platform-injected) or the
SDK's get_database_instance(). One connection per request by default; uses
a connection pool when PG_POOL_ENABLED is true (default).
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import psycopg
from databricks.sdk import WorkspaceClient
from psycopg_pool import ConnectionPool

from .config import settings

logger = logging.getLogger(__name__)

TOKEN_LIFETIME_SECONDS = 50 * 60

_lock = threading.Lock()
_token: str | None = None
_token_created_at: float = 0.0
_host: str | None = None
_ws: WorkspaceClient | None = None
_pool: ConnectionPool | None = None


def _client() -> WorkspaceClient:
    global _ws
    if _ws is None:
        _ws = WorkspaceClient()
    return _ws


def _get_host() -> str:
    global _host
    if settings.pghost:
        return settings.pghost
    if _host is None:
        instance = _client().database.get_database_instance(settings.lakebase_instance)
        _host = instance.read_write_dns
    return _host


def _get_user() -> str:
    if settings.pguser:
        return settings.pguser
    client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    if client_id:
        return client_id
    return _client().current_user.me().user_name


def _get_token() -> str:
    global _token, _token_created_at
    if settings.pgpassword:
        return settings.pgpassword
    with _lock:
        now = time.monotonic()
        if _token and (now - _token_created_at) < TOKEN_LIFETIME_SECONDS:
            return _token
        cred = _client().database.generate_database_credential(
            request_id=str(uuid.uuid4()),
            instance_names=[settings.lakebase_instance],
        )
        _token = cred.token
        _token_created_at = now
        return _token


class _LakebaseConnection(psycopg.Connection):
    @classmethod
    def connect(cls, conninfo: str = "", **kwargs: Any) -> _LakebaseConnection:
        host = _get_host()
        user = _get_user()
        token = _get_token()
        kwargs.update(
            {
                "host": host,
                "port": settings.pgport,
                "dbname": settings.lakebase_database,
                "user": user,
                "password": token,
                "sslmode": settings.pgsslmode,
                "options": f"-c search_path={settings.lakebase_schema}",
                "connect_timeout": 15,
            }
        )
        return super().connect(conninfo, **kwargs)


def get_connection() -> psycopg.Connection:
    host = _get_host()
    user = _get_user()
    token = _get_token()
    logger.debug(
        "connect host=%s user=%s port=%s db=%s",
        host,
        user,
        settings.pgport,
        settings.lakebase_database,
    )
    return psycopg.connect(
        host=host,
        port=settings.pgport,
        dbname=settings.lakebase_database,
        user=user,
        password=token,
        sslmode=settings.pgsslmode,
        options=f"-c search_path={settings.lakebase_schema}",
        connect_timeout=15,
    )


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is not None:
        return _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(
                connection_class=_LakebaseConnection,
                min_size=settings.pg_pool_min,
                max_size=settings.pg_pool_max,
                max_lifetime=45 * 60,
                max_idle=5 * 60,
                timeout=10,
                open=False,
            )
        return _pool


@contextmanager
def transaction() -> Generator[psycopg.Connection, None, None]:
    if not settings.pg_pool_enabled:
        conn = get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    with get_pool().connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def query(sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    if not settings.pg_pool_enabled:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            conn.close()

    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [desc[0] for desc in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def execute(sql: str, params: tuple[Any, ...] | None = None) -> int:
    if not settings.pg_pool_enabled:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                conn.commit()
                return cur.rowcount
        finally:
            conn.close()

    with get_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        conn.commit()
        return cur.rowcount
