"""FastAPI application entrypoint."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.routes import auth, incidents, services, system
from app.core.config import settings
from app.core.database import SessionLocal, init_db, wait_for_db
from app.core.logging import setup_logging
from app.services.seed import seed


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    setup_logging("backend")
    if not settings.database_url.startswith("sqlite"):
        wait_for_db()
    init_db()
    with SessionLocal() as db:
        seed(db)
    logger.info("SmartMonitor API started (OpenRouter: {}, Telegram: {})",
                "on" if settings.openrouter_enabled else "off", "on" if settings.telegram_enabled else "off")
    yield


app = FastAPI(title="SmartMonitor API", version="1.0.0", lifespan=lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error: {}", exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


for module in (auth, services, incidents, system):
    app.include_router(module.router)


# Optional: serve the SPA directly (local development without nginx)
if settings.frontend_dir and Path(settings.frontend_dir).is_dir():
    frontend = Path(settings.frontend_dir)
    app.mount("/css", StaticFiles(directory=frontend / "css"), name="css")
    app.mount("/js", StaticFiles(directory=frontend / "js"), name="js")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(frontend / "index.html")
