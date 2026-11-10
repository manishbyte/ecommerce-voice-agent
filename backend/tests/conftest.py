"""Test fixtures: SQLite (aiosqlite) stands in for PostgreSQL; LangGraph uses its in-memory saver.
No Groq / Gnani calls are made: with no API keys the agents use their deterministic paths, and no real
refunds or payments exist anywhere (all money movement is simulated records)."""
from __future__ import annotations

import os

os.environ.setdefault("GROQ_API_KEY", "")
os.environ.setdefault("GNANI_API_KEY", "")

import pytest_asyncio  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database.connection import dispose_engine, get_sessionmaker, init_engine, init_schema  # noqa: E402
from app.database.seed import seed_database  # noqa: E402


@pytest_asyncio.fixture
async def db(tmp_path):
    settings = get_settings()
    init_engine(settings, url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await init_schema(settings)
    await seed_database(get_sessionmaker(), settings.seed_file)
    yield get_sessionmaker()
    await dispose_engine()


@pytest_asyncio.fixture
async def graph(db):
    from langgraph.checkpoint.memory import InMemorySaver

    from app.agents.graph import build_graph
    return build_graph(InMemorySaver())


@pytest_asyncio.fixture
async def make_conversation(db):
    from sqlalchemy import select

    from app.models import Conversation, Customer

    async def _make(customer_id: str | None) -> str:
        async with db() as s:
            cust = (await s.execute(select(Customer).where(Customer.customer_id == customer_id))).scalar_one_or_none() if customer_id else None
            conv = Conversation(customer_pk=cust.id if cust else None)
            s.add(conv)
            await s.commit()
            return str(conv.id)
    return _make
