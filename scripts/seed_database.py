"""Manually seed (idempotent):  python scripts/seed_database.py   (the API also does this on startup)"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from app.core.logging import setup_logging  # noqa: E402
from app.database.connection import dispose_engine, get_sessionmaker, init_engine, init_schema  # noqa: E402
from app.database.seed import seed_database  # noqa: E402


async def main() -> None:
    s = get_settings()
    setup_logging(s.log_level)
    init_engine(s)
    await init_schema(s)
    print("inserted:", await seed_database(get_sessionmaker(), s.seed_file))
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
