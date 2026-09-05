from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
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


@app.get("/api/health")
async def health() -> dict:
    result: dict = {
        "status": "ok",
        "instance": settings.lakebase_instance,
        "database": settings.lakebase_database,
        "schema": settings.lakebase_schema,
    }
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        result["db"] = "connected"
    except Exception as exc:
        result["status"] = "degraded"
        result["db"] = f"error: {type(exc).__name__}"
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
