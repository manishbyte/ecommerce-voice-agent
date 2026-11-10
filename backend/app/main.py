"""FastAPI application: lifespan wiring for DB, seed data, checkpointer, graph and voice."""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.database.connection import dispose_engine, get_sessionmaker, init_engine, init_schema
from app.database.seed import seed_database
from app.dependencies import resources

if sys.platform == "win32":  # psycopg async requires the selector loop on Windows
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

log = logging.getLogger("app")


async def _init_checkpointer(settings):
    """AsyncPostgresSaver on its own pool + schema; in-memory saver only for SQLite test runs."""
    if settings.database_url.startswith("sqlite"):
        try:
            from langgraph.checkpoint.memory import InMemorySaver as Saver
        except ImportError:  # older langgraph
            from langgraph.checkpoint.memory import MemorySaver as Saver
        resources.checkpointer_kind = "memory (test mode)"
        return Saver(), None
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        conninfo=settings.checkpoint_dsn, max_size=10, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row,
                "options": f"-c search_path={settings.checkpoint_schema}"})
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()                       # idempotent: creates checkpoint tables once
    resources.checkpointer_kind = f"postgres (schema {settings.checkpoint_schema})"
    return saver, pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    logging.getLogger("gnani").setLevel(logging.WARNING)
    init_engine(settings)
    await init_schema(settings)
    counts = await seed_database(get_sessionmaker(), settings.seed_file)
    resources.startup_notes.append(f"seed inserted: {counts}")
    resources.checkpointer, resources.checkpoint_pool = await _init_checkpointer(settings)

    from app.agents.graph import build_graph
    from app.voice.language_config import validate_against_sdk

    resources.graph = build_graph(resources.checkpointer)
    resources.startup_notes.extend(validate_against_sdk())
    resources.ready = True
    log.info("Application ready")
    try:
        yield
    finally:
        resources.ready = False
        resources.shutting_down = True                    # 1. stop accepting new voice sessions
        from app.voice.voice_session import ACTIVE_SESSIONS

        await asyncio.gather(*(s.shutdown() for s in list(ACTIVE_SESSIONS.values())), return_exceptions=True)  # 2.
        if resources.checkpoint_pool is not None:         # 3. close the checkpointer pool
            await resources.checkpoint_pool.close()
        await dispose_engine()                            # 4. dispose SQLAlchemy engine


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="E-commerce Voice Support Agent", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})

    app.include_router(api_router)
    return app


app = create_app()
