"""NEXUS Observatory API -- FastAPI application with WebSocket support."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from nexus_core.database import get_engine, dispose_engine, ensure_database_compatibility

from nexus_api.routers import (
    activity,
    agents,
    civilization,
    economy,
    evolution,
    files,
    knowledge_graph,
    marketplace,
    objectives,
    observatory,
    pipeline,
    reports,
    securities,
    telemetry,
)
from nexus_api.websocket import router as ws_router, start_notify_listener, stop_notify_listener


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create engine on startup, start WS listener, dispose on shutdown."""
    engine = get_engine()
    await ensure_database_compatibility()
    await start_notify_listener()
    yield
    await stop_notify_listener()
    await dispose_engine()


app = FastAPI(
    title="NEXUS Observatory API",
    version="0.1.0",
    description="Real-time dashboard API for the NEXUS self-evolving agent research civilization.",
    lifespan=lifespan,
)

# CORS middleware -- allow localhost origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Health endpoint ───────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health-check endpoint."""
    return {"status": "ok", "service": "nexus-api"}


# ── API routers ───────────────────────────────────────────────────────────

app.include_router(agents.router)
app.include_router(files.router)
app.include_router(activity.router)
app.include_router(civilization.router)
app.include_router(observatory.router)
app.include_router(objectives.router)
app.include_router(knowledge_graph.router)
app.include_router(reports.router)
app.include_router(economy.router)
app.include_router(marketplace.router)
app.include_router(securities.router)
app.include_router(telemetry.router)
app.include_router(evolution.router)
app.include_router(pipeline.router)
app.include_router(ws_router)

# ── Static file serving for dashboard (mount last, after all routers) ────

_dashboard_dist = Path(__file__).resolve().parent.parent.parent / "nexus-dashboard" / "dist"
if _dashboard_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_dashboard_dist), html=True), name="dashboard")


# ── Entry point ───────────────────────────────────────────────────────────

def run():
    """CLI entry point for ``nexus-api`` command."""
    import uvicorn

    uvicorn.run(
        "nexus_api.main:app",
        host="0.0.0.0",
        port=int(os.environ.get("NEXUS_API_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    run()
