from __future__ import annotations

import logging
import os
from pathlib import Path

import anyio.to_thread
import psycopg_pool
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .routers import bookings, catalog, seats

logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager

# How long a 503 from a saturated pool asks the client to wait before
# retrying. Deliberately short and fixed, not pg_pool_timeout itself: a
# request already waited up to pg_pool_timeout for a connection before this
# fires, so telling it to wait that long again would compound the latency
# instead of giving the pool a chance to drain (ADR-008).
POOL_RETRY_AFTER_SECONDS = 2


def _configure_thread_pool() -> int:
    """Bind FastAPI's sync-handler threadpool to the Lakebase pool it feeds.

    Must run inside a running event loop -- anyio scopes the limiter to the
    current loop, so this is called from the lifespan below, on the loop that
    goes on to serve requests. See config.py and ADR-008 for the sizing
    rationale.
    """
    limiter = anyio.to_thread.current_default_thread_limiter()
    limiter.total_tokens = settings.api_thread_pool_size
    if settings.api_thread_pool_size < settings.pg_pool_max:
        logger.warning(
            "api_thread_pool_size=%d is smaller than pg_pool_max=%d; "
            "pooled connections will sit idle under concurrent load",
            settings.api_thread_pool_size,
            settings.pg_pool_max,
        )
    logger.info(
        "Threadpool sized to %d threads (pg_pool_max=%d, pg_pool_timeout=%ss)",
        settings.api_thread_pool_size,
        settings.pg_pool_max,
        settings.pg_pool_timeout,
    )
    return settings.api_thread_pool_size


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.log_platform_vars()
    _configure_thread_pool()
    logger.info(
        "instance=%s database=%s schema=%s dist_exists=%s",
        settings.lakebase_instance,
        settings.lakebase_database,
        settings.lakebase_schema,
        DIST_DIR.is_dir(),
    )
    logger.info(
        "pghost=%s pguser=%s pgport=%s pgsslmode=%s client_id=%s",
        settings.pghost or "(not set)",
        settings.pguser or "(not set)",
        settings.pgport,
        settings.pgsslmode,
        os.environ.get("DATABRICKS_CLIENT_ID", "(not set)"),
    )

    if settings.pg_pool_enabled:
        try:
            pool = db.get_pool()
            pool.open(wait=False)
            logger.info("Connection pool opened (wait=False)")
        except Exception as exc:
            logger.error("Failed to open connection pool on startup: %s", exc)

    yield

    if settings.pg_pool_enabled:
        try:
            pool = db.get_pool()
            pool.close()
            logger.info("Connection pool closed")
        except Exception as exc:
            logger.error("Failed to close connection pool: %s", exc)


app = FastAPI(title="Movies Booking API", lifespan=lifespan)

DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.exception_handler(psycopg_pool.PoolTimeout)
async def _pool_saturated(
    request: Request, exc: psycopg_pool.PoolTimeout
) -> JSONResponse:
    # Every pooled connection was checked out for longer than pg_pool_timeout.
    # That is the pool correctly refusing to over-admit work, not a server
    # fault, so it gets a 503 + Retry-After rather than falling into the
    # catch-all 500 below (ADR-008). Registered separately from the generic
    # handler; Starlette resolves by the exception's MRO, so this fires
    # instead of it regardless of registration order.
    logger.warning("Pool saturated on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": str(POOL_RETRY_AFTER_SECONDS)},
        content={
            "detail": (
                "Service is busy -- the database connection pool is "
                "saturated. Retry shortly."
            ),
            "error": "PoolTimeout",
        },
    )


@app.exception_handler(Exception)
async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    if request.url.path.startswith("/api"):
        logger.error(
            "Unhandled %s on %s: %s", type(exc).__name__, request.url.path, exc
        )
        # Prototype: the error class and message go into `detail` so the SPA's
        # error box shows the real cause. Production would log the detail and
        # return an opaque message with a correlation id.
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"{type(exc).__name__}: {str(exc)[:500]}",
                "error": type(exc).__name__,
                "message": str(exc)[:500],
            },
        )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/health")
def health() -> dict:
    result: dict = {
        "status": "ok",
        "instance": settings.lakebase_instance,
        "database": settings.lakebase_database,
        "schema": settings.lakebase_schema,
        "pghost_injected": settings.pghost is not None,
        "pguser_injected": settings.pguser is not None,
        "pgpassword_injected": settings.pgpassword is not None,
        "client_id_set": bool(os.environ.get("DATABRICKS_CLIENT_ID")),
        # The ADR-008 relationship, visible at runtime and not just in code.
        "pg_pool_max": settings.pg_pool_max,
        "pg_pool_timeout": settings.pg_pool_timeout,
        "api_thread_pool_size": settings.api_thread_pool_size,
    }

    # Step 0: WorkspaceClient auth type
    try:
        ws = db._client()
        result["sdk_auth_type"] = ws.config.auth_type
    except Exception as exc:
        result["status"] = "degraded"
        result["sdk_error"] = f"{type(exc).__name__}: {exc}"
        return result

    # Step 1: WorkspaceClient + resolve host
    try:
        host = db._get_host()
        result["resolved_host"] = host[:40] + "..." if len(host) > 40 else host
    except Exception as exc:
        result["status"] = "degraded"
        result["host_error"] = f"{type(exc).__name__}: {exc}"
        return result

    # Step 2: resolve user
    try:
        user = db._get_user()
        result["resolved_user"] = user
    except Exception as exc:
        result["status"] = "degraded"
        result["user_error"] = f"{type(exc).__name__}: {exc}"
        return result

    # Step 3: get database credential (PGPASSWORD or generate_database_credential)
    try:
        token = db._get_token()
        result["token_ok"] = bool(token)
        result["token_source"] = (
            "PGPASSWORD" if settings.pgpassword else "generate_database_credential"
        )
    except Exception as exc:
        result["status"] = "degraded"
        result["token_error"] = f"{type(exc).__name__}: {exc}"
        return result

    # Step 4: connect and test SELECT
    try:
        # Direct connection proving the credential path end to end,
        # so it must not be served by a warm pooled connection that 
        # skips it.
        conn = db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            result["db"] = "connected"
        finally:
            conn.close()
    except Exception as exc:
        result["status"] = "degraded"
        result["db"] = f"error: {type(exc).__name__}: {exc}"
        logger.warning("Health check DB error: %s", exc)

    if settings.pg_pool_enabled:
        try:
            pool = db.get_pool()
            stats = pool.get_stats()
            result["pool_stats"] = {
                "pool_size": stats.get("pool_size", 0),
                "pool_available": stats.get("pool_available", 0),
                "requests_waiting": stats.get("requests_waiting", 0),
                "connections_num": stats.get("connections_num", 0),
            }
        except Exception as exc:
            result["pool_stats"] = f"error: {type(exc).__name__}: {exc}"

    return result


app.include_router(catalog.router)
app.include_router(seats.router)
app.include_router(bookings.router)

# SPA serving — must be registered after all API routes.
# StaticFiles handles /assets, favicon, etc.; the 404 handler provides
# history-mode fallback for vue-router paths.
if DIST_DIR.is_dir():
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="spa")


@app.exception_handler(404)
async def _spa_fallback(request, exc):
    # History-mode fallback: a non-/api path that StaticFiles could not resolve
    # is a vue-router route, so serve index.html and let the router match it.
    if not request.url.path.startswith("/api") and DIST_DIR.is_dir():
        index = DIST_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
    # Under /api the routers raise HTTPException(404, "Movie not found") and
    # friends. This handler sees those too, so it must preserve their detail —
    # flattening every miss to a generic string is what the SPA would then
    # show the user.
    detail = getattr(exc, "detail", None) or "Not found"
    return JSONResponse({"detail": detail}, status_code=404)
