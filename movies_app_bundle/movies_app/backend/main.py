from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import settings
from .routers import catalog, seats, bookings

logger = logging.getLogger(__name__)

app = FastAPI(title="Movies Booking API")

DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.on_event("startup")
async def _startup() -> None:
    settings.log_platform_vars()
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


@app.exception_handler(Exception)
async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    if request.url.path.startswith("/api"):
        logger.error("Unhandled %s on %s: %s", type(exc).__name__, request.url.path, exc)
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
async def health() -> dict:
    result: dict = {
        "status": "ok",
        "instance": settings.lakebase_instance,
        "database": settings.lakebase_database,
        "schema": settings.lakebase_schema,
        "pghost_injected": settings.pghost is not None,
        "pguser_injected": settings.pguser is not None,
        "pgpassword_injected": settings.pgpassword is not None,
        "client_id_set": bool(os.environ.get("DATABRICKS_CLIENT_ID")),
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
        result["token_source"] = "PGPASSWORD" if settings.pgpassword else "generate_database_credential"
    except Exception as exc:
        result["status"] = "degraded"
        result["token_error"] = f"{type(exc).__name__}: {exc}"
        return result

    # Step 4: connect and run SELECT 1
    try:
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
async def _spa_fallback(request, exc):  # noqa: ANN001
    if not request.url.path.startswith("/api") and DIST_DIR.is_dir():
        index = DIST_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
    return JSONResponse({"detail": "Not found"}, status_code=404)
