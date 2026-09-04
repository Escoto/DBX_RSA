"""Connectivity check for the Lakebase instance.

Proves the auth path the app will use: a short-lived OAuth credential minted through the
Databricks SDK, used as the Postgres password over TLS. Locally the identity is the CLI
profile user (DATABRICKS_CONFIG_PROFILE=movies); on Databricks Apps it is the app's
service principal (DATABRICKS_CLIENT_ID / DATABRICKS_CLIENT_SECRET are injected).

Usage (WSL):
    DATABRICKS_CONFIG_PROFILE=movies ~/.venvs/movies/bin/python src/seed/check_connection.py
"""

from __future__ import annotations

import os
import sys
import uuid

import psycopg
from databricks.sdk import WorkspaceClient

INSTANCE = os.environ.get("LAKEBASE_INSTANCE", "movies-app-dev")
DATABASE = os.environ.get("LAKEBASE_DATABASE", "movies")


def postgres_identity(w: WorkspaceClient) -> str:
    """Postgres role name: the SP client id on Databricks Apps, the user's email locally."""
    client_id = os.environ.get("DATABRICKS_CLIENT_ID")
    if client_id:
        return client_id
    return w.current_user.me().user_name


def main() -> int:
    w = WorkspaceClient()
    instance = w.database.get_database_instance(INSTANCE)
    host = os.environ.get("PGHOST") or instance.read_write_dns
    user = os.environ.get("PGUSER") or postgres_identity(w)
    # Token is valid for about an hour; never log it.
    cred = w.database.generate_database_credential(request_id=str(uuid.uuid4()), instance_names=[INSTANCE])

    print(f"instance={INSTANCE} state={instance.state} pg={instance.pg_version}")
    print(f"host={host} db={DATABASE} user={user}")

    with psycopg.connect(
        host=host,
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=DATABASE,
        user=user,
        password=cred.token,
        sslmode="require",
        connect_timeout=15,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("select version(), current_user, current_database()")
            version, current_user, current_db = cur.fetchone()
            print(f"connected: {version.split(',')[0]} as {current_user} on {current_db}")

            cur.execute(
                "select nspname from pg_namespace "
                "where nspname not like 'pg_%' and nspname <> 'information_schema' order by 1"
            )
            print("schemas:", [r[0] for r in cur.fetchall()])

            cur.execute("select rolname from pg_roles where rolname not like 'pg_%' order by 1")
            print("roles:", [r[0] for r in cur.fetchall()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
