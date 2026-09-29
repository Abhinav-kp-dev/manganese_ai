"""MnPulse API + static dashboard server."""
from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import pipeline
from .api.routes import public, router
from .auth import seed_users
from .state import STATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mnpulse")
FRONTEND_DIST = Path(os.getenv("MH_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist"))


def _bootstrap():
    try:
        STATE.seed_if_empty()
        seed_users()
        STATE.train()
        pipeline.start_scheduler()
        log.info("Ready: %s (%s mode, %.1fs)", STATE.model_version, STATE.data_mode, STATE.train_seconds)
    except Exception:
        log.exception("Bootstrap failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("MH_SYNC_BOOTSTRAP") == "1":
        _bootstrap()
    else:
        threading.Thread(target=_bootstrap, daemon=True).start()
    yield


app = FastAPI(title="MnPulse API", version="1.0.0", lifespan=lifespan,
              description="SIH26009 — reserve confidence mapping, shortfall forecasting and corrective actions for MOIL.")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("MH_CORS_ORIGINS", "http://localhost:5173").split(","),
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(public)
app.include_router(router)

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = (FRONTEND_DIST / path).resolve()
        if path and f.is_file() and FRONTEND_DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
