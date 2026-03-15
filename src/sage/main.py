"""SAGE – Student Article Grading Engine – FastAPI entry point."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import settings

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="SAGE",
    description="Student Article Grading Engine – LLM-powered batch essay grading",
    version="1.0.0",
)

# API routes
app.include_router(router)

# Static files (frontend)
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


def main():
    import uvicorn

    uvicorn.run(
        "sage.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
