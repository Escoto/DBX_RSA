"""Entrypoint: python -m backend.serve"""

from __future__ import annotations

import logging

import uvicorn

from .config import settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=settings.app_port,
        log_level="info",
    )
