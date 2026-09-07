from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

PLATFORM_VARS = [
    "DATABRICKS_HOST",
    "DATABRICKS_CLIENT_ID",
    "DATABRICKS_APP_PORT",
    "PGHOST",
    "PGPORT",
    "PGDATABASE",
    "PGUSER",
    "PGPASSWORD",
    "PGSSLMODE",
]


class Settings:
    def __init__(self) -> None:
        # Fallbacks below only matter if LAKEBASE_* is unset. On the deployed
        # app these are always injected by resources/app.yml's
        # apps.movies_app.config.env (bundle-templated per target); locally,
        # export them per CLAUDE.md §7. The literals here match the `dev`
        # target's resolved names and are not target-derived -- update them
        # if the base names or target change and this ever gets hit for real.
        self.lakebase_instance = os.environ.get("LAKEBASE_INSTANCE", "movies-app-dev")
        self.lakebase_database = os.environ.get("LAKEBASE_DATABASE", "movies_dev")
        self.lakebase_schema = os.environ.get("LAKEBASE_SCHEMA", "movies")
        self.pghost: str | None = os.environ.get("PGHOST")
        self.pgport = int(os.environ.get("PGPORT", "5432"))
        self.pguser: str | None = os.environ.get("PGUSER")
        self.pgpassword: str | None = os.environ.get("PGPASSWORD")
        self.pgsslmode = os.environ.get("PGSSLMODE", "require")
        self.app_port = int(os.environ.get("DATABRICKS_APP_PORT", "8000"))

        self.pg_pool_min = int(os.environ.get("PG_POOL_MIN", "2"))
        self.pg_pool_max = int(os.environ.get("PG_POOL_MAX", "10"))
        self.pg_pool_enabled = (
            os.environ.get("PG_POOL_ENABLED", "true").lower() == "true"
        )
        # Seconds a thread waits for a pooled connection before psycopg_pool
        # raises PoolTimeout. Was a literal `timeout=10` inside db.py's
        # ConnectionPool(...); pulled out here so it can be reasoned about,
        # tuned, and tested alongside pool and threadpool size (ADR-008).
        self.pg_pool_timeout = float(os.environ.get("PG_POOL_TIMEOUT", "10"))

        # FastAPI runs every sync `def` handler in anyio's threadpool, default
        # 40 threads -- a number with no relationship to this app's pool of
        # PG_POOL_MAX=10 connections. Left alone, up to 40 requests can be
        # admitted at once, each thread then queuing for one of 10 connections
        # and parking for up to PG_POOL_TIMEOUT seconds before PoolTimeout.
        # Sizing the threadpool to pg_pool_max plus a small headroom (ADR-008)
        # means almost every admitted thread finds a connection immediately,
        # and any concurrency beyond that queues cheaply as a suspended
        # coroutine waiting for a thread token -- no OS thread, no contention
        # on the pool's own wait queue -- instead of piling up inside
        # psycopg_pool for the full timeout. The headroom covers blocking work
        # that does not go through the pool, chiefly /api/health's direct
        # get_connection() call.
        self.api_thread_pool_size = int(
            os.environ.get("API_THREAD_POOL_SIZE", str(self.pg_pool_max + 4))
        )

    def log_platform_vars(self) -> None:
        present = [v for v in PLATFORM_VARS if os.environ.get(v)]
        logger.info("Platform-injected env vars: %s", present or "none")


settings = Settings()
