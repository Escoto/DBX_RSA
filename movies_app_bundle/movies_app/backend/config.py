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
        self.lakebase_instance = os.environ.get("LAKEBASE_INSTANCE", "movies-app-dev")
        self.lakebase_database = os.environ.get("LAKEBASE_DATABASE", "movies")
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

    def log_platform_vars(self) -> None:
        present = [v for v in PLATFORM_VARS if os.environ.get(v)]
        logger.info("Platform-injected env vars: %s", present or "none")


settings = Settings()
