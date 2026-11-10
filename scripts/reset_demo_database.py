"""DESTRUCTIVE: drop all demo tables (+ LangGraph checkpoint schema) and re-seed from data/customers.json.

    python scripts/reset_demo_database.py --yes

Never runs automatically; the application itself never deletes data on startup.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.database.connection import dispose_engine, get_engine, get_sessionmaker, init_engine, init_schema  # noqa: E402
from app.database.seed import seed_database  # noqa: E402


async def main() -> None:
    if "--yes" not in sys.argv:
        sys.exit("Refusing to run without --yes (this deletes ALL demo data, conversations and checkpoints).")
    s = get_settings()
    init_engine(s)
    import app.models  # noqa: F401
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        if get_engine().dialect.name == "postgresql":
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{s.checkpoint_schema}" CASCADE'))
    await init_schema(s)
    print("reseeded:", await seed_database(get_sessionmaker(), s.seed_file))
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
