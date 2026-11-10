"""Async SQLAlchemy engine / session management."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.database.base import Base

log = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings, *, url: str | None = None) -> AsyncEngine:
    global _engine, _sessionmaker
    target = url or settings.database_url
    is_sqlite = target.startswith("sqlite")
    _engine = create_async_engine(target) if is_sqlite else create_async_engine(target, pool_pre_ping=True)
    if is_sqlite:
        @event.listens_for(_engine.sync_engine, "connect")
        def _fk_on(dbapi_conn, _):  # pragma: no cover
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialised")
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        raise RuntimeError("Database engine not initialised")
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


async def init_schema(settings: Settings) -> None:
    """Create missing tables (never drops or alters existing ones)."""
    import app.models  # noqa: F401  (registers all tables on Base.metadata)

    engine = get_engine()
    async with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.checkpoint_schema}"'))
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database schema ready")


async def ping() -> bool:
    try:
        async with get_sessionmaker()() as s:
            await s.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
