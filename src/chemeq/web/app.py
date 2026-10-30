"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..config import Config
from ..core.grade import ensure_db
from ..core.queue import GradeQueue
from .routes import router

BASE_DIR = Path(__file__).resolve().parent


def create_app(cfg: Config, *, start_queue: bool = True) -> FastAPI:
    ensure_db(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        queue = app.state.queue
        if queue is not None:
            queue.start()
        try:
            yield
        finally:
            if queue is not None:
                queue.stop()

    app = FastAPI(title="ChemEq Grader", version="0.1.0", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    app.state.queue = GradeQueue(cfg) if start_queue else None
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    app.include_router(router)
    return app
