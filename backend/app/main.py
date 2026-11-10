
"""FastAPI application and Windows-compatible Uvicorn entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.database.connection import (
    dispose_engine,
    get_sessionmaker,
    init_engine,
    init_schema,
)
from app.database.seed import seed_database
from app.dependencies import resources


log = logging.getLogger("app")


# ---------------------------------------------------------
# 1. LangGraph Checkpointer Initialization
# ---------------------------------------------------------

async def _init_checkpointer(settings):
    """Initialize PostgreSQL or in-memory LangGraph checkpointer."""

    if settings.database_url.startswith("sqlite"):
        try:
            from langgraph.checkpoint.memory import InMemorySaver as Saver
        except ImportError:
            from langgraph.checkpoint.memory import MemorySaver as Saver

        resources.checkpointer_kind = "memory (test mode)"
        return Saver(), None

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(
        conninfo=settings.checkpoint_dsn,
        max_size=10,
        open=False,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
            "options": f"-c search_path={settings.checkpoint_schema}",
        },
    )

    await pool.open()

    saver = AsyncPostgresSaver(pool)
    await saver.setup()

    resources.checkpointer_kind = (
        f"postgres (schema {settings.checkpoint_schema})"
    )

    return saver, pool


# ---------------------------------------------------------
# 2. FastAPI Lifespan
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):

    log.info(
        "ACTIVE EVENT LOOP IN LIFESPAN: %s",
        type(asyncio.get_running_loop()).__name__,
    )

    settings = get_settings()

    setup_logging(settings.log_level)
    logging.getLogger("gnani").setLevel(logging.WARNING)

    # Initialize database
    init_engine(settings)
    await init_schema(settings)

    # Seed database
    counts = await seed_database(
        get_sessionmaker(),
        settings.seed_file,
    )

    resources.startup_notes.append(
        f"seed inserted: {counts}"
    )

    # Initialize LangGraph checkpointer
    (
        resources.checkpointer,
        resources.checkpoint_pool,
    ) = await _init_checkpointer(settings)

    # Initialize graph and voice configuration
    from app.agents.graph import build_graph
    from app.voice.language_config import validate_against_sdk

    resources.graph = build_graph(resources.checkpointer)

    resources.startup_notes.extend(
        validate_against_sdk()
    )

    resources.ready = True

    log.info("Application ready")

    try:
        yield

    finally:
        log.info("Application shutting down")

        resources.ready = False
        resources.shutting_down = True

        # Shutdown active voice sessions
        from app.voice.voice_session import ACTIVE_SESSIONS

        await asyncio.gather(
            *(
                session.shutdown()
                for session in list(ACTIVE_SESSIONS.values())
            ),
            return_exceptions=True,
        )

        # Close LangGraph PostgreSQL pool
        if resources.checkpoint_pool is not None:
            await resources.checkpoint_pool.close()

        # Dispose SQLAlchemy engine
        await dispose_engine()

        log.info("Application shutdown complete")


# ---------------------------------------------------------
# 3. FastAPI Application
# ---------------------------------------------------------

def create_app() -> FastAPI:

    settings = get_settings()

    app = FastAPI(
        title="E-commerce Voice Support Agent",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(
        request: Request,
        exc: AppError,
    ):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.message,
                "code": exc.code,
            },
        )

    app.include_router(api_router)

    return app


app = create_app()


# ---------------------------------------------------------
# 4. Uvicorn Entry Point
# ---------------------------------------------------------

async def run_server():

    config = uvicorn.Config(
    app,
    host="0.0.0.0",
    port=8000,
    reload=False,
    loop="asyncio",
    log_level="info",
)

    server = uvicorn.Server(config)

    print(
        "ACTIVE EVENT LOOP:",
        type(asyncio.get_running_loop()).__name__,
    )

    await server.serve()


# ---------------------------------------------------------
# 5. Main Execution
# ---------------------------------------------------------

if __name__ == "__main__":

    if sys.platform == "win32":

        asyncio.run(
            run_server(),
            loop_factory=asyncio.SelectorEventLoop,
        )

    else:

        asyncio.run(run_server())
