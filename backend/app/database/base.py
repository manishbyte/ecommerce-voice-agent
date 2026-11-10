from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Integer, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


# JSONB on PostgreSQL, plain JSON elsewhere (tests run on SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    """Naive UTC timestamp (dataset timestamps are naive too)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
