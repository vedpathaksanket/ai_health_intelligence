"""
backend/main.py
FastAPI application entry point.
Wires together routers, lifespan events, middleware, and static files.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from backend.core.config import settings
from backend.db.mongodb import connect_db, close_db
from backend.api.routes import air_quality, alerts, chat, websocket
from backend.services.ingestion import ingestion_service
from backend.services.alert_service import alert_service
from backend.utils.ws_manager import ws_manager

# ── Logging setup ─────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# ── Background scheduler ──────────────────────────────────────────────────────

async def _ingestion_loop() -> None:
    """Periodic ingestion task: fetch data → evaluate alerts → push WS."""
    logger.info(
        "Ingestion scheduler started | interval=%ds | cities=%s",
        settings.ingestion_interval_seconds,
        settings.monitored_cities,
    )
    while True:
        try:
            readings = await ingestion_service.ingest_cities()
            for reading in readings:
                new_alerts = await alert_service.evaluate_reading(reading)
                if new_alerts:
                    logger.info(
                        "Alerts triggered for %s: %d", reading.city, len(new_alerts)
                    )
            # Push live-data broadcast
            await ws_manager.broadcast_topic("live-data", {
                "type": "ingestion_complete",
                "cities": [r.city for r in readings],
                "count": len(readings),
            })
        except Exception as exc:
            logger.error("Ingestion loop error: %s", exc, exc_info=True)
        await asyncio.sleep(settings.ingestion_interval_seconds)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup
    await connect_db()
    task = asyncio.create_task(_ingestion_loop())
    logger.info("✅ Application started — %s", settings.app_name)
    yield
    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await ingestion_service.close()
    await close_db()
    logger.info("⛔ Application shut down.")


# ── App factory ───────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Real-time urban air quality monitoring with AI-powered health risk assessment, "
        "WebSocket alerts, and statistical trend analysis."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

API_PREFIX = "/api"
app.include_router(air_quality.router, prefix=API_PREFIX)
app.include_router(alerts.router,      prefix=API_PREFIX)
app.include_router(chat.router,        prefix=API_PREFIX)
app.include_router(websocket.router)

# ── Static files & templates ──────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
templates = Jinja2Templates(directory="frontend/templates")


@app.get("/", include_in_schema=False)
async def serve_dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Meta"])
async def health_check():
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "ws_connections": ws_manager.total_connections,
    }


@app.get("/ws/stats", tags=["Meta"])
async def ws_connection_stats():
    return ws_manager.stats()


# ── Global exception handler ──────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."},
    )


# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
